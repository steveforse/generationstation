"""Quantization-aware replacement for longcat_video.lora.merge_lora_into_model (used by longcat_driver.py).
Upstream raises shape mismatch on q4/q8 DiTs (weight is bit-packed). Here: dequantize ->
add delta -> requantize (same bits/group_size). Lossy but works."""
import mlx.core as mx
from mlx.utils import tree_flatten, tree_unflatten
import longcat_video.lora as L

def merge_lora_into_model(mx_model, lora_state_dict, multiplier=1.0, target_prefix=""):
    grouped = L.group_lora_tensors(lora_state_dict)
    params = dict(tree_flatten(mx_model.parameters()))
    applied, unmapped = [], []
    for mp, group in grouped.items():
        k = f"{target_prefix}.{mp}" if target_prefix else mp
        wk = k + ".weight"
        if wk not in params:
            unmapped.append(mp); continue
        w = params[wk]
        delta = L.compute_merged_delta(group, multiplier=multiplier)
        sk, bk = k + ".scales", k + ".biases"
        if sk in params:   # quantized linear
            scales, biases = params[sk], params[bk]
            in_f = delta.shape[1]
            bits = w.shape[1] * 32 // in_f
            gs = in_f // scales.shape[1]
            full = mx.dequantize(w, scales, biases, group_size=gs, bits=bits).astype(mx.float32)
            full = full + delta.astype(mx.float32)
            nw, ns, nb = mx.quantize(full.astype(scales.dtype), group_size=gs, bits=bits)
            mx.eval(nw, ns, nb)
            mx_model.update(tree_unflatten([(wk, nw), (sk, ns), (bk, nb)]))  # drop old weights immediately
            params[wk], params[sk], params[bk] = nw, ns, nb
            del full
        else:
            if delta.shape != w.shape:
                raise ValueError(f"shape mismatch {mp}: {delta.shape} vs {w.shape}")
            params[wk] = w + delta.astype(w.dtype)
            mx.eval(params[wk])
            mx_model.update(tree_unflatten([(wk, params[wk])]))
        applied.append(mp)
    mx.eval(mx_model.parameters())
    return {"applied": applied, "unmapped": unmapped}

L.merge_lora_into_model = merge_lora_into_model
