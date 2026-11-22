"""Qwen Image 2.1 picture worker. Runs in its own environment (PyTorch, Diffusers, torchao, PEFT).

Config options (from runtimes.json, per preset):
    pipeline_dir       Diffusers folder with text_encoder/, vae/, processor/, scheduler/ (Qwen-Image-2.1-Turbo's).
    transformer        The transformer weights: a Diffusers folder or a single .safetensors file.
    transformer_format "torchao" (a Diffusers folder saved with torchao), "comfy_fp8" (ComfyUI scaled FP8) or
                       "comfy_nvfp4" (ComfyUI NVFP4: 4-bit maths on RTX 50-series; older cards keep the
                       weights in 4 bits and expand them per layer).
    turbo              true for Qwen-Image-2.1-Turbo: its own 8-step schedule, no guidance.
    lightning          Optional path to the Lightning 4-step adapter, enabling the "quick" quality.
    base_scheduler_dir Scheduler config for full-step generation (Qwen-Image-2.1's), when not turbo.

Start settings: transformer_precision ("fp8" | "bf16"; for NVFP4 weights, the maths on cards
    without 4-bit support), compile (default true), text_encoder_precision ("fp8" | "bf16"),
    offload (true: swap every part between system RAM and the card per image; false: keep the
    transformer and VAE on the card), text_encoder_device ("cpu", the default: keep the
    text encoder in system RAM and run it on the processor, so nothing moves between images; "cuda").
Inputs: prompt, negative_prompt, size ("square" | "portrait" | "landscape" | "wide" or "WxH"),
    quality ("quick" | "best"; Turbo has one), seed.
"""
import json
import random
import time
from pathlib import Path

from gs_worker import serve

DTYPE = None  # torch.bfloat16, set on first use so importing this module does not import torch
BEST_STEPS = 35
BEST_CFG = 5.0
LIGHTNING_SIGMAS = [1.0, 0.75, 0.5, 0.25]


def _torch():
    global DTYPE
    import torch
    DTYPE = torch.bfloat16
    return torch


def _dequantize_to_bf16(module):
    """Replace torchao-quantized weights with plain BF16 copies (lossless for FP8 sources)."""
    torch = _torch()
    for child in module.modules():
        for name, param in list(child.named_parameters(recurse=False)):
            if type(param.data) is not torch.Tensor and hasattr(param.data, "dequantize"):
                setattr(child, name, torch.nn.Parameter(param.data.dequantize().to(DTYPE), requires_grad=False))


def _load_comfy_fp8(path, config_dir):
    """ComfyUI "scaled FP8": FP8 weights with a scale per tensor, under Diffusers' own tensor names."""
    torch = _torch()
    from accelerate import init_empty_weights
    from diffusers import QwenImage21Transformer2DModel
    from safetensors.torch import load_file

    raw = load_file(str(path))
    state = {}
    for key, tensor in raw.items():
        if key == "scaled_fp8" or key.endswith((".scale_weight", ".scale_input")):
            continue
        scale = raw.get(key[: -len("weight")] + "scale_weight") if key.endswith(".weight") else None
        value = tensor.to(torch.float32) * scale.to(torch.float32) if scale is not None else tensor
        state[key] = value.to(DTYPE)
    with init_empty_weights():
        model = QwenImage21Transformer2DModel.from_config(
            QwenImage21Transformer2DModel.load_config(str(Path(config_dir) / "transformer")))
    model.load_state_dict(state, strict=True, assign=True)
    return model.to(DTYPE).eval()


FP8_MAX = 448.0
E2M1_VALUES = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, -0.0, -0.5, -1.0, -1.5, -2.0, -3.0, -4.0, -6.0]


def _nvfp4_linear_class():
    torch = _torch()

    class NVFP4WeightLinear(torch.nn.Linear):
        """A linear layer that keeps NVFP4 weights in 4 bits and expands them just before each
        matmul, for cards without 4-bit maths (RTX 40-series). The weights take a quarter of BF16's
        memory; the matmul runs in FP8 (default) or BF16. When the block is compiled, the
        expansion fuses into one kernel per layer."""

        def __init__(self, packed, block_scales, tensor_scale, bias, fp8_maths=True):
            torch.nn.Module.__init__(self)  # skip Linear's own weight allocation
            self.out_features, self.in_features = packed.shape[0], packed.shape[1] * 2
            self.register_buffer("packed", packed)               # uint8 [out, in/2], high nibble first
            self.register_buffer("block_scales", block_scales)   # float8_e4m3fn [out, in/16], row-major
            self.register_buffer("tensor_scale", tensor_scale)   # float32 scalar
            self.register_buffer("values", torch.tensor(E2M1_VALUES, dtype=torch.float32, device=packed.device))
            self.bias = bias
            self.fp8_maths = fp8_maths
            self.register_buffer("weight_scale", self.weight_bf16().abs().amax().float() / FP8_MAX)

        @property
        def weight(self):
            # A stand-in that takes no memory: adapter libraries (PEFT, for Lightning) only read
            # the weight's shape, dtype and device.
            return torch.empty(1, 1, dtype=DTYPE, device=self.packed.device).expand(self.out_features, self.in_features)

        def weight_bf16(self):
            codes = torch.stack((self.packed >> 4, self.packed & 0x0F), dim=-1).int()
            values = self.values[codes].view(self.out_features, self.in_features // 16, 16)
            scales = self.block_scales.float().unsqueeze(-1) * self.tensor_scale
            return (values * scales).view(self.out_features, self.in_features).to(DTYPE)

        def forward(self, x):
            if not self.fp8_maths:
                return torch.nn.functional.linear(x, self.weight_bf16(), self.bias)
            # FP8 maths with one scale per tensor: about twice BF16's speed on RTX 40-series, adding
            # the usual FP8 rounding (about 3% on a layer's output).
            weight = (self.weight_bf16() / self.weight_scale).to(torch.float8_e4m3fn)
            flat = x.reshape(-1, self.in_features)
            x_scale = flat.abs().amax().float().clamp(min=1e-12) / FP8_MAX
            out = torch._scaled_mm((flat / x_scale).to(torch.float8_e4m3fn), weight.t(), scale_a=x_scale,
                                   scale_b=self.weight_scale, bias=self.bias, out_dtype=DTYPE)
            return out.view(*x.shape[:-1], self.out_features)

    return NVFP4WeightLinear


def _load_comfy_nvfp4(path, config_dir, fp8_maths=True, log=print):
    """ComfyUI NVFP4: 4-bit weights with FP8 scales per block of 16 and one FP32 scale per tensor.

    On RTX 50-series and newer the matmuls run as real 4-bit maths through torchao. Older cards
    keep the weights in 4 bits and expand each layer to BF16 when it runs (NVFP4WeightLinear).
    ComfyUI's layout, checked against the FP8 file: block scales are already in cuBLAS's swizzled
    order, the whole-tensor scale is stored as-is, and the two 4-bit values in each byte are high
    nibble first (the opposite order to torchao's packing).
    """
    torch = _torch()
    from accelerate import init_empty_weights
    from diffusers import QwenImage21Transformer2DModel
    from safetensors.torch import load_file
    from torchao.prototype.mx_formats.utils import from_blocked

    native = torch.cuda.get_device_capability() >= (10, 0)
    if not native:
        log(f"[worker] this card has no 4-bit maths; NVFP4 weights will be expanded to {'FP8' if fp8_maths else 'BF16'} per layer")
    raw = load_file(str(path), device="cuda")
    # ComfyUI fuses each feed-forward's gate_layer and proj into one gate_up matrix (gate rows first).
    # Split it back; rows split cleanly because swizzled scales are stored in 128-row tiles.
    for key in [key for key in raw if key.endswith(".gate_up.comfy_quant")]:
        fused = key[: -len("gate_up.comfy_quant")]
        for suffix in (".weight", ".weight_scale"):
            gate, proj = raw.pop(fused + "gate_up" + suffix).chunk(2)
            raw[fused + "gate_layer" + suffix], raw[fused + "proj" + suffix] = gate.contiguous(), proj.contiguous()
        for suffix in (".weight_scale_2", ".comfy_quant"):
            raw[fused + "gate_layer" + suffix] = raw[fused + "proj" + suffix] = raw.pop(fused + "gate_up" + suffix)
    quantized = {key[: -len(".comfy_quant")] for key in raw if key.endswith(".comfy_quant")}
    state = {key: value.to(DTYPE) for key, value in raw.items()
             if key.rsplit(".", 1)[0] not in quantized or key.endswith(".bias")}
    with init_empty_weights():
        model = QwenImage21Transformer2DModel.from_config(
            QwenImage21Transformer2DModel.load_config(str(Path(config_dir) / "transformer")))
    missing, unexpected = model.load_state_dict(state, strict=False, assign=True)
    leftover = set(missing) - {name + ".weight" for name in quantized}
    if leftover or unexpected:
        raise ValueError(f"NVFP4 file does not match the model: missing {sorted(leftover)[:5]}, unexpected {unexpected[:5]}")
    if native:
        from torchao.prototype.mx_formats.nvfp4_tensor import NVFP4Tensor, QuantizeTensorToNVFP4Kwargs

        activations = QuantizeTensorToNVFP4Kwargs(use_dynamic_per_tensor_scale=True, use_triton_kernel=False,
                                                  is_swizzled_scales=True)
    else:
        NVFP4WeightLinear = _nvfp4_linear_class()
    for name in quantized:
        packed, scales = raw.pop(name + ".weight"), raw.pop(name + ".weight_scale")
        tensor_scale = raw.pop(name + ".weight_scale_2").float()
        linear = model.get_submodule(name)
        if native:
            weight = NVFP4Tensor(((packed & 0x0F) << 4) | (packed >> 4), scales, 16, DTYPE,
                                 per_tensor_scale=tensor_scale, is_swizzled_scales=True,
                                 act_quant_kwargs=activations)
            linear.weight = torch.nn.Parameter(weight, requires_grad=False)
        else:
            rows, blocks = packed.shape[0], packed.shape[1] * 2 // 16
            scales = from_blocked(scales.flatten(), rows, blocks).contiguous()
            parent, _, child = name.rpartition(".")
            setattr(model.get_submodule(parent), child,
                    NVFP4WeightLinear(packed, scales, tensor_scale, linear.bias, fp8_maths))
    del raw
    return model.to("cuda").eval()


def _compile_nvfp4_activations(log=print):
    """Fuse the per-layer 4-bit conversion of activations into one kernel each.

    Uncompiled, that conversion is a chain of small operations costing about four times the 4-bit
    matmul itself, which makes NVFP4 slower than FP8. Compiling needs Triton ("triton-windows" on
    Windows); without it NVFP4 still works, just slowly.
    """
    import importlib.util
    import os

    if importlib.util.find_spec("triton") is None:
        log("[worker] Triton is not installed; NVFP4 will run uncompiled and slower than FP8")
        return
    os.environ.setdefault("TRITON_DEFAULT_FP_FUSION", "1")
    torch = _torch()
    import torchao.prototype.mx_formats.nvfp4_tensor as nvfp4

    # Prompt length and image size change the activation shapes, so compile for any shape.
    nvfp4.nvfp4_quantize = torch.compile(nvfp4.nvfp4_quantize, dynamic=True)
    nvfp4.to_blocked = torch.compile(nvfp4.to_blocked, dynamic=True)


def _compile_blocks(transformer, log=print):
    """Compile each transformer block (Diffusers' regional compilation) when Triton is available.

    Fuses the FP8 or NVFP4 activation conversion and the small operations around each matmul.
    Compiling happens during the first image at each quality and size, which is then slower.
    """
    import importlib.util
    import os

    if importlib.util.find_spec("triton") is None:
        log("[worker] Triton is not installed; running uncompiled")
        return
    os.environ.setdefault("TRITON_DEFAULT_FP_FUSION", "1")
    import torch._dynamo.config

    # Headroom over PyTorch's default of 8 compiled versions per block (Lightning on and off, image
    # sizes); past the limit blocks silently fall back to slow uncompiled code.
    torch._dynamo.config.recompile_limit = 64
    transformer.compile_repeated_blocks(dynamic=True)


def load_transformer(options, settings=None, log=print):
    from diffusers import QwenImage21Transformer2DModel

    _torch()
    fmt = options.get("transformer_format", "torchao")
    if fmt == "torchao":
        model = QwenImage21Transformer2DModel.from_pretrained(options["transformer"], torch_dtype=DTYPE)
        _dequantize_to_bf16(model)
        return model.eval()
    if fmt == "comfy_fp8":
        return _load_comfy_fp8(options["transformer"], options["pipeline_dir"])
    if fmt == "comfy_nvfp4":
        _compile_nvfp4_activations()
        fp8_maths = (settings or {}).get("transformer_precision", "fp8") == "fp8"
        return _load_comfy_nvfp4(options["transformer"], options["pipeline_dir"], fp8_maths, log)
    raise ValueError(f"Unknown transformer_format {fmt!r}")


def _quantize_fp8(module, weight_only=False, granularity="tensor"):
    """FP8 weights; unless weight_only, the matrix maths also runs in FP8.

    Per-tensor scaling is the default because PyTorch's FP8 matmul does not support per-row scales
    on consumer cards (RTX 4080 / 5090) in the 2.14 builds: "Rowwise scaling is not currently supported".
    """
    from torchao.quantization import (
        Float8DynamicActivationFloat8WeightConfig, Float8WeightOnlyConfig, PerRow, PerTensor, quantize_)

    if weight_only:
        config = Float8WeightOnlyConfig()
    else:
        config = Float8DynamicActivationFloat8WeightConfig(granularity=PerRow() if granularity == "row" else PerTensor())
    quantize_(module, config)


def load(config, log=print):
    torch = _torch()
    from diffusers import AutoencoderKLQwenImage21, FlowMatchEulerDiscreteScheduler, QwenImage21Pipeline
    from transformers import Qwen3VLForConditionalGeneration, Qwen3VLProcessor

    options, settings = config["options"], config.get("settings", {})
    pipeline_dir = Path(options["pipeline_dir"])
    started = time.perf_counter()

    transformer = load_transformer(options, settings, log)
    nvfp4 = options.get("transformer_format") == "comfy_nvfp4"
    if not nvfp4 and settings.get("transformer_precision", "fp8") == "fp8":
        _quantize_fp8(transformer)
    log(f"[worker] transformer ready in {time.perf_counter() - started:.0f} s")

    text_encoder = Qwen3VLForConditionalGeneration.from_pretrained(pipeline_dir / "text_encoder", dtype=DTYPE).eval()
    encoder_on_cpu = settings.get("text_encoder_device", "cpu") == "cpu"
    if not encoder_on_cpu and settings.get("text_encoder_precision", "bf16") == "fp8":
        # Weight-only: the encoder runs once per image, so memory matters more than speed here.
        _quantize_fp8(text_encoder.model.language_model, weight_only=True)
    vae = AutoencoderKLQwenImage21.from_pretrained(pipeline_dir / "vae", torch_dtype=DTYPE).eval()
    processor = Qwen3VLProcessor.from_pretrained(pipeline_dir / "processor")

    turbo = bool(options.get("turbo"))
    scheduler_dir = pipeline_dir if turbo else Path(options.get("base_scheduler_dir") or pipeline_dir)
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(scheduler_dir / "scheduler")
    sample_sigmas = json.loads((pipeline_dir / "model_index.json").read_text())["sample_sigmas"] if turbo else None
    pipe = QwenImage21Pipeline(scheduler=scheduler, vae=vae, text_encoder=text_encoder, processor=processor,
                               transformer=transformer, sample_sigmas=sample_sigmas)

    lightning = options.get("lightning")
    if lightning and not turbo:
        path = Path(lightning)
        pipe.load_lora_weights(str(path.parent), weight_name=path.name, adapter_name="lightning")
        pipe.disable_lora()

    if settings.get("compile", True):
        _compile_blocks(transformer)
    offload = settings.get("offload", False)
    if encoder_on_cpu:
        # Nothing moves per image: the encoder lives in system RAM and runs on the processor
        # (about half a second per prompt in full BF16), and only its output goes to the card.
        if offload:
            raise ValueError("Choose offload or text_encoder_device 'cpu', not both.")
        pipe.transformer.to("cuda")
        pipe.vae.to("cuda")
    elif offload:
        if nvfp4 and torch.cuda.get_device_capability() >= (10, 0):
            raise ValueError("4-bit NVFP4 weights stay on the card; turn offload off.")
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    log(f"[worker] pipeline ready in {time.perf_counter() - started:.0f} s")
    return {"pipe": pipe, "turbo": turbo, "encoder_on_cpu": encoder_on_cpu, "lightning": bool(lightning and not turbo),
            "best_scheduler": scheduler.config,
            "torch": torch}


SHAPES = {"square": (1024, 1024), "portrait": (768, 1152), "landscape": (1152, 768), "wide": (1344, 768)}


def _size(text):
    if str(text or "square").lower() in SHAPES:
        return SHAPES[str(text or "square").lower()]
    width, _, height = str(text).lower().partition("x")
    width, height = int(width), int(height)
    if not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise ValueError("Size must be between 256 and 2048 pixels on each side.")
    return width, height


def _encode_on_cpu(pipe, torch, text):
    with torch.inference_mode():
        embeds, mask, _ = pipe.encode_prompt(text, device=torch.device("cpu"))
    return embeds.to("cuda"), None if mask is None else mask.to("cuda")  # no mask when nothing is padded


def render(model, inputs, on_step=None):
    """Make one image. Returns (PIL image, details). on_step(done, total) is called after each step."""
    from diffusers import FlowMatchEulerDiscreteScheduler

    pipe, torch = model["pipe"], model["torch"]
    width, height = _size(inputs.get("size"))
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    quality = "turbo" if model["turbo"] else inputs.get("quality") or "best"
    # No prompt cache: it only skips recomputing the text tokens (tens, against thousands of image
    # tokens), and with it the compiled blocks recompile for every new prompt length (8-20 s each).
    args = {"prompt": inputs["prompt"], "width": width, "height": height, "use_kv_cache": False,
            "generator": torch.Generator("cpu").manual_seed(seed)}
    if model["turbo"]:
        steps, args["true_cfg_scale"] = 8, 1.0
    elif quality == "quick" and model["lightning"]:
        pipe.enable_lora()
        pipe.set_adapters(["lightning"], [1.0])
        pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(model["best_scheduler"], shift_terminal=None)
        steps = len(LIGHTNING_SIGMAS)
        args.update(sigmas=LIGHTNING_SIGMAS, num_inference_steps=steps, true_cfg_scale=1.0)
    else:
        if model["lightning"]:
            pipe.disable_lora()
        pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(model["best_scheduler"])
        steps = BEST_STEPS
        # A single space keeps true CFG on; an empty negative prompt would disable it.
        args.update(num_inference_steps=steps, true_cfg_scale=BEST_CFG,
                    negative_prompt=inputs.get("negative_prompt") or " ")
    if model["encoder_on_cpu"]:
        for name in ("prompt", "negative_prompt"):
            if name in args:
                embeds, mask = _encode_on_cpu(pipe, torch, args.pop(name))
                args[f"{name}_embeds"], args[f"{name}_embeds_mask"] = embeds, mask
    if on_step:
        def step_end(pipeline, index, timestep, tensors):
            on_step(index + 1, steps)
            return tensors
        args["callback_on_step_end"] = step_end
    image = pipe(**args).images[0]
    return image, {"seed": seed, "steps": steps, "quality": quality, "width": width, "height": height}


def generate(model, inputs, job):
    job.report("Reading the description")
    started = time.perf_counter()
    try:
        image, details = render(model, inputs, lambda done, total: job.report(f"Painting, step {done} of {total}"))
    except BaseException:
        model["torch"].cuda.empty_cache()  # a cancel or error mid-picture: give the memory back
        raise
    image.save(job.output(f"picture-{details['seed']}.png", "image/png"))
    job.detail(**details)
    job.thumbnail(image)
    torch = model["torch"]
    print(f"[worker] picture {details['width']}x{details['height']} {details['quality']}: "
          f"{time.perf_counter() - started:.1f} s, peak {torch.cuda.max_memory_reserved() / 2**30:.1f} GiB reserved",
          flush=True)
    torch.cuda.reset_peak_memory_stats()
    # Hand cached working memory back between pictures: the card may also drive the display or a game.
    torch.cuda.empty_cache()
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {details['seed']}")


if __name__ == "__main__":
    serve(load, generate, cleanup=lambda model: model["torch"].cuda.empty_cache())
