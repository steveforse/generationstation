"""MiniMax H3 video worker: short clips with sound from a description. Runs in its own environment
(PyTorch, Diffusers 0.43 with MiniMax H3 support, torchao, PEFT, PyAV).

Config options (from runtimes.json, per preset):
    pipeline_dir      MiniMaxAI/MiniMax-H3 Diffusers folder (configs, tokenizer, schedulers, vae/, audio_vae/).
                      Its own text_encoder/ weights are not read; only text_encoder/config.json.
    transformer       ComfyUI NVFP4 "pruned" transformer file (minimax_h3_fl2va_pruned_nvfp4.safetensors).
    text_encoder_dir  Qwen3-VL-32B-Instruct weights (stock, or an uncensored copy with the same layout).
    turbo_lora        Optional Turbo v4 add-on (larryvrh minimax_h3_turbo_v4_step600_ema.safetensors); enables quality "turbo".
    turbo_grid        h3_silu_temb_grid.safetensors, which the Turbo v4 add-on's time-modulation part needs.

Start settings: compile (default true).
Inputs: mode ("text" | "frames"), prompt, sounds, music, style ("none" | "cinematic" | "handheld" | "animated"),
    first / last (frames mode: [{"path", ...}] uploaded pictures the clip starts from / ends on),
    shape ("landscape 16:9" | "portrait 9:16" | "square 1:1" | "portrait 4:5" | "classic 4:3", and
    "match picture" with pictures), resolution ("240p" ... "720p", "1080p" = 720p resized | "custom" with width, height),
    first_crop / last_crop ("x,y,w,h" framing), length (seconds, "5" | "10" | "15"), quality ("turbo" | "standard" | "high" | "extreme"), seed.

Needs an RTX 50-series card: the transformer runs as real 4-bit maths (torchao NVFP4).
The text encoder stays in system RAM and runs on the processor (about 2 s per prompt).
"""
import os
import random
import re
import time
from pathlib import Path

from gs_worker import serve

os.environ.setdefault("HF_HUB_OFFLINE", "1")

DTYPE = None  # torch.bfloat16, set on first use so importing this module does not import torch
FPS = 24
# Model calls per clip for each quality. Turbo runs with the Turbo v4 add-on; the others without it.
# MiniMax's own default is 50 (Diffusers' num_inference_steps=50).
STEPS = {"turbo": 4, "standard": 20, "high": 30, "extreme": 50}
QUALITY_ALIASES = {"quick": "turbo", "best": "standard"}  # jobs saved before the four levels
TEXT_LAYERS = 50  # H3 conditions on the hidden state after decoder layer 50, before the final norm
# Short edge per resolution, a multiple of 32 as H3 needs (so "720p" is 704 and "360p" 352).
SHORT_EDGE = {"240p": 256, "360p": 352, "480p": 480, "540p": 544, "720p": 704,
              "1080p (fast resize)": 704, "1080p (AI upscale)": 544}
# Resolutions rendered smaller and enlarged afterwards (1080p does not fit on the card): their final short edge.
# "fast resize" renders at 720p and resizes (Lanczos); "AI upscale" renders at 540p and runs FlashVSR+.
UPSCALED = {"1080p (fast resize)": 1080, "1080p (AI upscale)": 1080}
RESOLUTION_ALIASES = {"1080p (upscaled)": "1080p (fast resize)"}  # jobs saved before the AI upscale existed
MAX_PIXELS = 1280 * 720  # measured to fit on the RTX 5090 for 5 s; H3's own canvas limit is 768 x 1344
SHAPE_ALIASES = {"landscape": "landscape 16:9", "portrait": "portrait 9:16", "square": "square 1:1"}  # older jobs
# H3 takes 17n + 5 frames: 5.2 s and 10.1 s at 24 fps. The plugin offers only 5 s: on the RTX 5090 a
# 10 s clip peaked at 29.7 GiB, more than admission allows the card (2026-11-21).
LENGTHS = {"5": 124, "10": 243, "15": 345}  # 17n+5 frames at 24 fps; H3 takes at most 360
# Above this many video pixels per clip (frames x width x height) the decoder and transformer take turns on the
# card (see _take_turns): a 5 s 720p clip is about 109 million, a 10 s 540p clip about 127 million.
TAKE_TURNS_ABOVE = 100_000_000
STYLES = {"none": "", "cinematic": "Live-action, cinematic, ", "handheld": "Live-action, handheld, ",
          "animated": "3D animation, stylized, "}
STYLE_ALIASES = {"as written": "none"}  # jobs saved before the rename
RAW_PREFIX = "integrated_multimodal_description:"


def _torch():
    global DTYPE
    import torch
    DTYPE = torch.bfloat16
    return torch


# ---------------------------------------------------------------- prompt

SPEECH = re.compile(r"\b(says?|said|asks?|asked|shouts?|shouted|whispers?|whispered|sings?|sang|replies|replied)"
                    r"(\s*[:,]?\s*)[\"“]([^\"”]+)[\"”]", re.IGNORECASE)


def _dialogue(text):
    """Turn `she says: "Hello"` into H3's spoken-line markup, so the words are spoken aloud.
    Every line is given one speaker (S1); for several speakers write the full H3 prompt."""
    return SPEECH.sub(lambda m: f"(S1) {m.group(1)}: <d>[English] {m.group(3).strip()}</d>", text)


def frame_instruction(first, last, seconds):
    """MiniMax's alignment line for keyframes (its prompt guide, sections 2.1 and 3), word for word."""
    end = f"{seconds:.2f}"
    if first and last:
        return ("How the reference pictures align with the target video \u2014 Picture 1 (from Shot 1) aligns with "
                f"the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {end}-second "
                "mark of the target video.")
    if first:
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    if last:
        return ("How the reference pictures align with the target video \u2014 <Picture 1> (from [Shot 1]) aligns "
                f"with the {end}-second mark of the target video.")
    return ""


def build_prompt(inputs, first=False, last=False, seconds=LENGTHS["5"] / FPS):
    """H3 is trained on a structured prompt (picture and action, ambient sound, music), preceded by an
    alignment line when pictures anchor the start or end. A prompt that already starts with the structure
    (or with the alignment line) is used as written."""
    text = inputs["prompt"].strip()
    instruction = frame_instruction(first, last, seconds)
    if text.startswith(("For the target video", "How the reference pictures")):
        return text  # a full H3 prompt with its own alignment line
    if text.lower().startswith(RAW_PREFIX):
        return f"{instruction}\n\n{text}" if instruction else text
    style = STYLES.get(STYLE_ALIASES.get(inputs.get("style"), inputs.get("style")) or "none", "")
    sounds = (inputs.get("sounds") or "").strip() or "Natural sounds that match the scene."
    music = (inputs.get("music") or "").strip() or "None."
    body = (f"{RAW_PREFIX} [Shot 1] {style}{_dialogue(text)}\n\n"
            f"overall_soundscape: {sounds}\n\nnon_diegetic_music: {music}")
    return f"{instruction}\n\n{body}" if instruction else body


VIDEO_USES = {"show what's in them", "copy camera and motion", "continue them", "edit them"}
AUDIO_USES = {"voice to imitate", "soundtrack to keep", "music style"}
LOOKS = {"cinematic": "The target video uses a live-action, cinematic style.",
         "handheld": "The target video uses a live-action, handheld documentary style.",
         "animated": "The target video uses a stylized 3D animation style.", "none": ""}
MENTION = re.compile(r"\b(picture|image|photo|video|audio|voice|clip|song|track)\s*#?\s*(\d{1,2})\b", re.IGNORECASE)
NOTE = re.compile(r"^\s*(picture|image|photo|video|audio)\s*#?\s*(\d{1,2})\s*[:\-]\s*(.+)$", re.IGNORECASE)


def _kind(word):
    word = word.lower()
    return "picture" if word in {"picture", "image", "photo"} else "video" if word == "video" else "audio"


def build_reference_prompt(inputs, pictures, videos, audios):
    """MiniMax's full-reference prompt (its reference prompt guide): subject_definitions, summary,
    retention_analysis, detailed_description, overall_soundscape, non_diegetic_music.

    Every picture becomes a subject; videos and audio clips play the role chosen on the form. Mentions
    such as "picture 2" or "audio 1" in the description are turned into the guide's labels. Optional
    notes ("Picture 1: my white Samoyed") describe what each reference shows.
    """
    text = inputs["prompt"].strip()
    if text.lower().startswith("subject_definitions:"):
        return text  # a full reference prompt, used as written
    notes = {}
    for line in (inputs.get("notes") or "").splitlines():
        match = NOTE.match(line)
        if match:
            notes[(_kind(match.group(1)), int(match.group(2)))] = match.group(3).strip().rstrip(".")
    video_use = inputs.get("video_use") or "show what's in them"
    audio_use = inputs.get("audio_use") or "voice to imitate"
    definitions, retention, tasks, labels = [], [], [], {}
    subject = 0
    for index in range(1, pictures + 1):
        subject += 1
        labels[("picture", index)] = f"<Subject {subject}>"
        what = notes.get(("picture", index), "the main subject shown")
        definitions.append(f"<Subject {subject}> is {what} in <Picture {index}>, as it appears there.")
        retention.append(f"<Subject {subject}> (appears in [Shot 1]): fully_preserved - its appearance in "
                         f"<Picture {index}> is retained.")
    for index in range(1, videos + 1):
        what = notes.get(("video", index))
        if video_use == "show what's in them":
            subject += 1
            labels[("video", index)] = f"<Subject {subject}>"
            definitions.append(f"<Subject {subject}> is {what or 'the main subject'} in <Video {index}>.")
            retention.append(f"<Subject {subject}> (appears in [Shot 1]): fully_preserved - its appearance and "
                             f"movement in <Video {index}> are retained.")
        elif video_use == "copy camera and motion":
            labels[("video", index)] = f"<Video {index}>"
            definitions.append(f"<Video {index}> is the camera-movement and pacing reference for the target video"
                               + (f", showing {what}." if what else "."))
            retention.append(f"<Video {index}> (camera movement and pacing): weak_reference - its camera movement "
                             "and rhythm guide the target video.")
        elif video_use == "continue them":
            labels[("video", index)] = f"<Video {index}>"
            definitions.append(f"<Video {index}> is the source video that the target video continues from.")
            retention.append(f"<Video {index}> (continuation source): fully_preserved - the target video picks up "
                             "from its final state.")
            tasks.append("video continuation")
        else:
            labels[("video", index)] = f"<Video {index}>"
            definitions.append(f"<Video {index}> is the source video for the target video edit.")
            retention.append(f"<Video {index}> (edit source): partially_preserved - its content is kept except for "
                             "the changes described.")
            tasks.append("video editing")
    if pictures or (videos and video_use in {"show what's in them", "copy camera and motion"}):
        tasks.insert(0, "reference generation")
    soundtrack = music_style = voice = None
    for index in range(1, audios + 1):
        labels[("audio", index)] = f"<Audio {index}>"
        if audio_use == "soundtrack to keep":
            soundtrack = soundtrack or f"<Audio {index}>"
            definitions.append(f"<Audio {index}> is the soundtrack reused in the target video.")
            retention.append(f"<Audio {index}>: fully_copy - <Audio {index}> is reused 1:1 as the target video's "
                             "complete final audio track.")
            tasks.append("audio reuse")
        elif audio_use == "music style":
            music_style = music_style or f"<Audio {index}>"
            definitions.append(f"<Audio {index}> is the music-style reference for the background music.")
            retention.append(f"<Audio {index}>: reference - its music style guides the background music without "
                             "copying the original signal.")
            tasks.append("audio reference")
        else:
            voice = voice or f"<Audio {index}>"
            definitions.append(f"<Audio {index}> is the voice-timbre reference for the speaker (S{index}).")
            retention.append(f"<Audio {index}>: reference - its voice timbre guides the delivery of (S{index}) "
                             "without copying the original signal.")
            tasks.append("audio reference")
    tasks = list(dict.fromkeys(tasks)) or ["reference generation"]

    def label(match):
        return labels.get((_kind(match.group(1)), int(match.group(2))), match.group(0))

    body = _dialogue(MENTION.sub(label, text))
    first = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0]
    prefix = "The target video is an edited version of <Video 1>. " if "video editing" in tasks else ""
    look = LOOKS.get(STYLE_ALIASES.get(inputs.get("style"), inputs.get("style")) or "none", "")
    if voice and "(S1)" in body:
        body += f" (S1) speaks with the voice timbre referenced from {voice}."
    sounds = (inputs.get("sounds") or "").strip() or "Natural sounds that match the scene."
    if soundtrack:
        sounds = f"{soundtrack} plays as the complete soundtrack. {sounds}"
    music = (inputs.get("music") or "").strip()
    music = f"Background music in the style of {music_style}. {music}".strip() if music_style else music or "N/A"
    return "\n\n".join([
        "subject_definitions:\n" + "\n".join(definitions),
        f"summary:\n[{' + '.join(tasks)}] {prefix}{first}",
        "retention_analysis:\n" + "\n".join(retention),
        "detailed_description:\n" + (f"{look}\n" if look else "") + f"[Shot 1] {body}",
        f"overall_soundscape:\n{sounds}",
        f"non_diegetic_music:\n{music}",
    ])


# ---------------------------------------------------------------- pruned transformer (ComfyUI layout)

RENAME = [
    ("token_refiner.blocks.", "token_refiner.refiner_blocks."),
    ("video_patch_proj.", "proj_in."), ("audio_patch_proj.", "audio_proj_in."),
    ("condition_proj.", "context_embedder."),
    ("final_layer.norm.", "norm_out.norm."), ("final_layer.adaln_proj.linear.", "norm_out.linear."),
    ("final_layer.video_out.", "proj_out."), ("final_layer.audio_out.", "audio_proj_out."),
    (".attn.q_norm.", ".attn.norm_q."), (".attn.k_norm.", ".attn.norm_k."),
    (".attn.out_proj", ".attn.to_out.0"), (".mlp.fc1", ".ff.net.0.proj"), (".mlp.fc2", ".ff.net.2"),
]


def diffusers_name(key):
    """ComfyUI tensor name -> Diffusers MiniMaxH3Transformer3DModel name."""
    if key.startswith("blocks."):
        key = "transformer_blocks." + key[len("blocks."):]
    for old, new in RENAME:
        key = key.replace(old, new)
    return key


def _curve_classes():
    torch = _torch()

    class CurveTime(torch.nn.Module):
        """Replaces time_proj + time_embedder for "pruned" checkpoints: the timestep t in [0, 1]
        picks an interpolated row of the checkpoint's adaln_t_table (and, for the Turbo v4 add-on,
        of its silu(t_emb) grid, concatenated after it)."""

        def __init__(self, table, grid=None):
            super().__init__()
            self.register_buffer("table", table.float())
            self.register_buffer("grid", None if grid is None else grid.float())

        @staticmethod
        def _lerp(table, t):
            pos = t.float().clamp(0, 1) * (table.shape[0] - 1)
            i0 = pos.floor().long().clamp(max=table.shape[0] - 2)
            return torch.lerp(table[i0], table[i0 + 1], (pos - i0).unsqueeze(1))

        def forward(self, t):
            out = self._lerp(self.table, t)
            return out if self.grid is None else torch.cat([out, self._lerp(self.grid, t)], dim=1)

    class CurveLinear(torch.nn.Module):
        """A time-modulation projection on the table row (FP32, no SiLU), plus the Turbo v4
        add-on's low-rank correction on the silu(t_emb) grid row while Turbo is on."""

        def __init__(self, weight, bias, curve_dim):
            super().__init__()
            self.weight = torch.nn.Parameter(weight.float(), requires_grad=False)
            self.bias = torch.nn.Parameter(bias.float(), requires_grad=False)
            self.curve_dim = curve_dim
            self.lora_a = self.lora_b = None
            self.lora_on = False

        def forward(self, temb):
            x = torch.nn.functional.linear(temb[:, : self.curve_dim].float(), self.weight, self.bias)
            if self.lora_on and self.lora_a is not None:
                x = x + (temb[:, self.curve_dim:].float() @ self.lora_a.t()) @ self.lora_b.t()
            return x.to(DTYPE)

    return CurveTime, CurveLinear


def _patch_curve_forwards(model):
    """Pruned checkpoints project the table row directly: no SiLU before the modulation linears."""
    from diffusers.models.transformers import transformer_minimax_h3 as h3

    def block_forward(self, temb):
        return self.linear(temb).view(-1, 6 * self.hidden_size).chunk(6, dim=-1)

    def out_forward(self, hidden_states, temb, timestep_indices):
        shift, scale = self.linear(temb).chunk(2, dim=-1)
        hidden_states = self.norm(hidden_states)
        return hidden_states * (1.0 + scale.index_select(0, timestep_indices)) + shift.index_select(0, timestep_indices)

    for block in model.transformer_blocks:
        block.adaln_proj.forward = block_forward.__get__(block.adaln_proj, h3.MiniMaxH3AdaLayerNormModulation)
    model.norm_out.forward = out_forward.__get__(model.norm_out, h3.MiniMaxH3AdaLayerNormOut)


def _nvfp4_linear(packed, scales, tensor_scale, bias):
    """ComfyUI NVFP4 (high nibble first, swizzled block scales) as a torchao NVFP4Tensor."""
    torch = _torch()
    from torchao.prototype.mx_formats.nvfp4_tensor import (
        NVFP4Tensor,
        QuantizeTensorToNVFP4Kwargs,
    )

    activations = QuantizeTensorToNVFP4Kwargs(use_dynamic_per_tensor_scale=True, use_triton_kernel=False,
                                              is_swizzled_scales=True)
    weight = NVFP4Tensor(((packed & 0x0F) << 4) | (packed >> 4), scales, 16, DTYPE, per_tensor_scale=tensor_scale,
                         is_swizzled_scales=True, act_quant_kwargs=activations)
    linear = torch.nn.Linear(packed.shape[1] * 2, packed.shape[0], bias=bias is not None, device="meta")
    linear.weight = torch.nn.Parameter(weight, requires_grad=False)
    if bias is not None:
        linear.bias = torch.nn.Parameter(bias, requires_grad=False)
    return linear


def load_transformer(path, pipeline_dir, grid=None, log=print):
    """Load the ComfyUI NVFP4 pruned H3 transformer into Diffusers' model, straight onto the card.

    Layout differences from Diffusers, checked against the FP8 file: fused q/k/v rows are split
    (block-scale tiles are 128 rows, so the split is exact), feed-forward fc1 is stored [gate; value]
    and Diffusers wants [value; gate], and the time modulation uses the checkpoint's own table.
    """
    torch = _torch()
    from accelerate import init_empty_weights
    from diffusers import MiniMaxH3Transformer3DModel
    from safetensors.torch import load_file

    if torch.cuda.get_device_capability() < (10, 0):
        raise RuntimeError("MiniMax H3 here needs an RTX 50-series card (4-bit NVFP4 maths).")
    CurveTime, CurveLinear = _curve_classes()
    raw = load_file(str(path), device="cuda")
    quantized = [key[: -len(".comfy_quant")] for key in raw if key.endswith(".comfy_quant")]
    table = raw.pop("adaln_t_table")
    raw.pop("rope.inv_freq", None)
    with init_empty_weights():
        model = MiniMaxH3Transformer3DModel.from_config(
            MiniMaxH3Transformer3DModel.load_config(str(Path(pipeline_dir) / "transformer")))
    model.time_proj = torch.nn.Identity()
    model.time_embedder = CurveTime(table, grid)

    def install(name, module):
        parent, _, child = name.rpartition(".")
        setattr(model.get_submodule(parent), child, module)

    def rows(tensor, n):
        return [part.contiguous() for part in tensor.chunk(n)]

    for name in quantized:
        target = diffusers_name(name)
        bias = raw.pop(name + ".bias", None)
        bias = None if bias is None else bias.to(DTYPE)
        packed, scales = raw.pop(name + ".weight"), raw.pop(name + ".weight_scale")
        if scales.dtype == torch.uint8:
            scales = scales.view(torch.float8_e4m3fn)
        tensor_scale = raw.pop(name + ".weight_scale_2").float()
        raw.pop(name + ".comfy_quant")
        if name.endswith("attn.qkv_proj"):
            biases = rows(bias, 3) if bias is not None else [None] * 3
            for part, p, s, b in zip("qkv", rows(packed, 3), rows(scales, 3), biases):
                install(target.replace("qkv_proj", f"to_{part}"), _nvfp4_linear(p, s, tensor_scale, b))
        elif name.endswith("mlp.fc1"):
            (pg, pv), (sg, sv) = rows(packed, 2), rows(scales, 2)
            b = None if bias is None else torch.cat(bias.chunk(2)[::-1])
            install(target, _nvfp4_linear(torch.cat([pv, pg]), torch.cat([sv, sg]), tensor_scale, b))
        else:
            install(target, _nvfp4_linear(packed, scales, tensor_scale, bias))

    for key in [key for key in raw if key.endswith("adaln_proj.linear.weight")]:
        base = key[: -len(".weight")]
        install(diffusers_name(key)[: -len(".weight")], CurveLinear(raw.pop(key), raw.pop(base + ".bias"), table.shape[1]))

    state = {}
    for key, value in raw.items():
        new = diffusers_name(key)
        if new.endswith(("ff.net.0.proj.weight", "ff.net.0.proj.bias")):
            value = torch.cat(value.chunk(2)[::-1])
        if ".attn.qkv_proj." in key:  # the token refiner's unquantized fused q/k/v
            for part, piece in zip("qkv", value.chunk(3)):
                state[new.replace("qkv_proj", f"to_{part}")] = piece
            continue
        state[new] = value
    del raw
    keep_fp32 = ("proj_in.", "audio_proj_in.", "proj_out.", "audio_proj_out.")
    state = {key: value if key.startswith(keep_fp32) else value.to(DTYPE) for key, value in state.items()}
    _, unexpected = model.load_state_dict(state, strict=False, assign=True)
    on_meta = [name for name, p in list(model.named_parameters()) + list(model.named_buffers()) if p.device.type == "meta"]
    if unexpected or on_meta:
        raise ValueError(f"Transformer file does not match the model: unexpected {unexpected[:5]}, missing {on_meta[:5]}")
    _patch_curve_forwards(model)
    return model.to("cuda").eval().requires_grad_(False)


def load_turbo(model, path, log=print):
    """Turbo v4: a LoRA on the attention and feed-forward layers (through PEFT, adapter "turbo")
    plus low-rank corrections on the time-modulation projections."""
    torch = _torch()
    from diffusers.loaders.lora_conversion_utils import (
        _convert_non_diffusers_minimax_h3_lora_to_diffusers,
    )
    from safetensors.torch import load_file

    weights = {key.removeprefix("diffusion_model."): value for key, value in load_file(str(path)).items()}
    adaln = {key: weights.pop(key) for key in list(weights) if ".adaln_proj." in key}
    for key in [key for key in adaln if key.endswith("lora_A.weight")]:
        base = key[: -len(".lora_A.weight")]
        linear = model.get_submodule(diffusers_name(base + ".weight")[: -len(".weight")])
        linear.lora_a = adaln[key].to("cuda", torch.float32)
        linear.lora_b = adaln[base + ".lora_B.weight"].to("cuda", torch.float32)
    converted = _convert_non_diffusers_minimax_h3_lora_to_diffusers(weights)
    converted = {key.removeprefix("transformer."): value.to(DTYPE) for key, value in converted.items()}
    model.load_lora_adapter(converted, adapter_name="turbo", prefix=None)
    log(f"[worker] Turbo add-on: {len(converted)} LoRA tensors, {len(adaln) // 2} time-modulation corrections")


def set_turbo(model, on):
    if on:
        model.enable_lora()
    else:
        model.disable_lora()
    for module in model.modules():
        if hasattr(module, "lora_on"):  # CurveLinear
            module.lora_on = on


# ---------------------------------------------------------------- text encoder (CPU)

def load_text_encoder(pipeline_dir, weights_dir, log=print):
    """Qwen3-VL-32B cut to its first 51 decoder layers, with its vision tower, BF16, in system RAM.

    H3 conditions on the hidden state after decoder layer 50 (`hidden_states[50]`). Diffusers reads it off
    a stack that has more than 50 layers, so one extra layer is kept; the other 13 and the language-model
    head are never loaded. The vision tower reads the pictures of the image modes.
    """
    torch = _torch()
    import json

    from accelerate import init_empty_weights
    from safetensors import safe_open
    from transformers import AutoConfig, Qwen3VLForConditionalGeneration

    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
    config = AutoConfig.from_pretrained(str(Path(pipeline_dir) / "text_encoder"))
    config.text_config.num_hidden_layers = TEXT_LAYERS + 1
    with init_empty_weights():
        encoder = Qwen3VLForConditionalGeneration(config)
    weights_dir = Path(weights_dir)
    index = json.loads((weights_dir / "model.safetensors.index.json").read_text())["weight_map"]
    wanted = {key: shard for key, shard in index.items()
              if key.startswith("model.visual.") or (key.startswith("model.language_model.") and (
                  ".layers." not in key or int(key.split(".layers.")[1].split(".")[0]) <= TEXT_LAYERS))}
    state = {}
    for shard in sorted(set(wanted.values())):
        with safe_open(str(weights_dir / shard), "pt") as f:
            for key in [key for key, s in wanted.items() if s == shard]:
                state[key] = f.get_tensor(key).to(DTYPE)
    missing, _ = encoder.load_state_dict(state, strict=False, assign=True)
    missing = [key for key in missing if key.startswith("model.")]
    if missing:
        raise ValueError(f"Text encoder weights are incomplete: {missing[:5]}")
    del state
    # Rotary tables and other buffers that are computed, not stored: materialize them on the processor.
    for module in encoder.modules():
        for name, buffer in list(module.named_buffers(recurse=False)):
            if buffer.device.type == "meta":
                raise ValueError(f"Text encoder buffer {name} was not initialized")
    return encoder.eval()


def build_encoders(blocks, pipeline_dir, text_encoder):
    """Per workflow, a small pipeline on the processor that turns the prompt (and pictures) into what the
    transformer reads: Diffusers' own presentation and encoding steps, with the CPU text encoder."""
    encoders = {}
    tokenizer = processor = None
    for workflow in WORKFLOWS:
        steps = blocks.get_workflow(workflow)
        for name in list(steps.sub_blocks):
            if name not in ("before_encode", "text_encoder"):
                steps.sub_blocks.pop(name)
        pipe = steps.init_pipeline(str(pipeline_dir))
        pipe.update_components(text_encoder=text_encoder)
        if tokenizer is None:
            pipe.load_components(names=["tokenizer", "processor"], pretrained_model_name_or_path=str(pipeline_dir))
            tokenizer, processor = pipe.tokenizer, pipe.processor
        else:
            pipe.update_components(tokenizer=tokenizer, processor=processor)
        encoders[workflow] = pipe
    return encoders


# ---------------------------------------------------------------- worker

WORKFLOWS = ("t2va", "fl2va", "ref2va")
# Which transformer each workflow runs on: the main one (text, pictures) or the reference one.
TRANSFORMER_OF = {"t2va": "main", "fl2va": "main", "ref2va": "ref"}
WORKFLOW_OF = {"text": "t2va", "frames": "fl2va", "reference": "ref2va"}
# How large reference pictures are read (their short edge in pixels). MiniMax's own 2048 costs about 6,000
# tokens per picture, read by the 32B prompt reader on the processor and again by the transformer each step.
DETAIL = {"standard": 1024, "high": 2048, "fast": 768}
# Reference videos are put on a canvas of this short edge (Diffusers' default is H3's full 768 x 1344 canvas,
# which with every frame kept is about twice the clip being made and overflows the card).
VIDEO_DETAIL = {"standard": 352, "high": 544, "fast": 256}


def _build_pipes(model, transformer, which):
    """Card pipelines for the workflows that run on `transformer`, sharing the decoders and schedulers."""
    torch = model["torch"]
    pipes = {}
    for workflow in [w for w in WORKFLOWS if TRANSFORMER_OF[w] == which]:
        steps = model["blocks"].get_workflow(workflow)
        steps.sub_blocks.pop("text_encoder")
        pipe = steps.init_pipeline(str(model["pipeline_dir"]))
        given = {**model["shared"], "transformer": transformer, "transformer_ref": transformer}
        pipe.update_components(**{name: value for name, value in given.items() if name in pipe._component_specs})
        names = [name for name in pipe._component_specs if getattr(pipe, name, None) is None]
        if names:
            pipe.load_components(names=names, dtype=DTYPE, pretrained_model_name_or_path=str(model["pipeline_dir"]))
        for name in pipe._component_specs:
            value = getattr(pipe, name, None)
            if name in ("transformer", "transformer_ref") or value is None:
                continue
            if isinstance(value, torch.nn.Module):
                value.to("cuda")
            model["shared"].setdefault(name, value)
        pipes[workflow] = pipe
    return pipes


def _use_transformer(model, which, log=print):
    """Put the main or the reference transformer on the card (only one fits beside the decoders)."""
    if model["active"] == which:
        return
    import gc

    torch = model["torch"]
    started = time.perf_counter()
    model["pipes"], model["transformer"] = {}, None
    gc.collect()
    torch.cuda.empty_cache()
    options = model["options"]
    turbo = options.get("turbo_lora") if which == "main" or options.get("turbo_for_reference") else None
    transformer = load_transformer(options["transformer" if which == "main" else "reference_transformer"],
                                   model["pipeline_dir"], model["grid"] if turbo else None, log)
    if turbo:
        load_turbo(transformer, turbo, log)
    if model["compile"]:
        import torch._dynamo
        from qwen_image_worker import _compile_blocks
        torch._dynamo.reset()  # the other transformer's compiled blocks would only count against the limit
        _compile_blocks(transformer, log)
    model.update(transformer=transformer, pipes=_build_pipes(model, transformer, which), active=which,
                 turbo=bool(turbo), turbo_on=bool(turbo))
    log(f"[worker] {which} transformer on the card in {time.perf_counter() - started:.0f} s")


def load(config, log=print):
    torch = _torch()
    from diffusers import ModularPipeline
    from safetensors.torch import load_file

    options, settings = config["options"], config.get("settings", {})
    pipeline_dir = Path(options["pipeline_dir"])
    started = time.perf_counter()
    model = {"torch": torch, "options": options, "pipeline_dir": pipeline_dir, "shared": {}, "active": None,
             "compile": settings.get("compile", True), "pipes": {}, "transformer": None,
             "grid": load_file(str(options["turbo_grid"]))["silu_t_emb_grid"] if options.get("turbo_lora") else None,
             "blocks": ModularPipeline.from_pretrained(str(pipeline_dir)).blocks}
    if model["compile"]:
        from qwen_image_worker import _compile_nvfp4_activations
        _compile_nvfp4_activations(log)
    _use_transformer(model, "main", log)
    log(f"[worker] card ready in {time.perf_counter() - started:.0f} s, "
        f"{torch.cuda.memory_allocated() / 2**30:.1f} GiB in use")
    text_encoder = load_text_encoder(pipeline_dir, options["text_encoder_dir"], log)
    model["encoders"] = build_encoders(model["blocks"], pipeline_dir, text_encoder)
    log(f"[worker] ready in {time.perf_counter() - started:.0f} s")
    return model


def _references(inputs):
    """The reference files as Diffusers' reference objects: pictures, then videos (without their own
    sound, so "audio N" always means the Nth audio clip), then audio clips."""
    from diffusers.modular_pipelines.minimax_h3 import (
        MiniMaxH3AudioReference,
        MiniMaxH3ImageReference,
        MiniMaxH3VideoReference,
    )

    pictures = [MiniMaxH3ImageReference.from_file(item["path"]) for item in inputs.get("images") or []]
    videos = []
    for item in inputs.get("videos") or []:
        video = MiniMaxH3VideoReference.from_file(item["path"])
        video.audio, video.sample_rate = None, None
        videos.append(video)
    audios = [MiniMaxH3AudioReference.from_file(item["path"]) for item in inputs.get("audio") or []]
    return pictures, videos, audios


def _picture(entries):
    from PIL import Image

    if not entries:
        return None
    with Image.open(entries[0]["path"]) as image:
        return image.convert("RGB")


def _round32(value):
    return max(256, min(1344, round(value / 32) * 32))


def _ratio(inputs, anchor=None):
    shape = SHAPE_ALIASES.get(inputs.get("shape"), inputs.get("shape")) or "landscape 16:9"
    if shape == "match picture" and anchor is not None:
        return anchor.width / anchor.height
    w, h = (int(part) for part in re.search(r"(\d+):(\d+)", shape if shape != "match picture" else "16:9").groups())
    return w / h


def _resolution(inputs):
    value = inputs.get("resolution") or "540p"
    return RESOLUTION_ALIASES.get(value, value)


def output_size(inputs, anchor=None):
    """The final frame size for upscaled resolutions (even numbers, the shape's exact proportions), or None."""
    short = UPSCALED.get(_resolution(inputs))
    if short is None:
        return None
    ratio = _ratio(inputs, anchor)
    long = round(short * max(ratio, 1 / ratio) / 2) * 2
    return (long, short) if ratio >= 1 else (short, long)


def canvas_size(inputs, anchor=None):
    """Width and height of the clip from shape and resolution (or the custom size).

    The resolution is the short edge; 'match picture' takes the proportions of `anchor`. The pixel count
    is kept within what fits on the card, shrinking both edges together when needed.
    """
    resolution = _resolution(inputs)
    if resolution == "custom":
        width, height = _round32(inputs["width"]), _round32(inputs["height"])
    else:
        ratio = _ratio(inputs, anchor)
        short = SHORT_EDGE.get(resolution, SHORT_EDGE["540p"])
        width, height = (_round32(short * ratio), short) if ratio >= 1 else (short, _round32(short / ratio))
    while width * height > MAX_PIXELS:
        width, height = _round32(width * 0.97), _round32(height * 0.97)
    return width, height


def _frame_crop(image, crop, width, height):
    """Apply the framing chosen on the preview ("x,y,w,h" fractions), then make the proportions exact."""
    if image is None:
        return None
    if crop:
        x, y, w, h = (float(part) for part in crop.split(","))
        box = (round(x * image.width), round(y * image.height), round((x + w) * image.width), round((y + h) * image.height))
        image = image.crop(box)
    return _cover(image, width, height)


def _cover(image, width, height):
    """Crop a picture to the canvas proportions around its centre, so it is never stretched: Diffusers
    stretches a keyframe whose proportions differ from the canvas."""
    if image is None:
        return None
    target = width / height
    if abs(image.width / image.height - target) < 0.01:
        return image
    if image.width / image.height > target:
        keep = round(image.height * target)
        left = (image.width - keep) // 2
        return image.crop((left, 0, left + keep, image.height))
    keep = round(image.width / target)
    top = (image.height - keep) // 2
    return image.crop((0, top, image.width, top + keep))


def _take_turns(model):
    """For large clips: the video decoder (about 10 GB) waits in system RAM while the transformer denoises, and
    the transformer waits there while the decoder decodes, so their working memory never adds up. Each move
    takes one to two seconds. Returns a function that restores both to the card."""
    torch, transformer = model["torch"], model["transformer"]
    vae = model["shared"]["vae"]
    vae.to("cuda")  # pictures and references are encoded before the first step
    for pipe in model["pipes"].values():
        # The pipeline takes its working device from the first component with weights (the transformer); with
        # the transformer in system RAM the audio decode would build its tensors there. Only these pipelines
        # are pinned to the card: the prompt readers share their class and must stay on the processor.
        if not getattr(pipe, "_pinned_to_card", False):
            pipe.__class__ = type("CardPinned" + type(pipe).__name__, (type(pipe),),
                                  {"_execution_device": property(lambda self: torch.device("cuda", 0)),
                                   "_pinned_to_card": True})

    def park_decoder(module, args):
        vae.to("cpu")
        torch.cuda.empty_cache()
        handle.remove()

    handle = transformer.register_forward_pre_hook(park_decoder)
    original = vae.decode

    def decode(*args, **kwargs):
        transformer.to("cpu")
        torch.cuda.empty_cache()
        vae.to("cuda")
        return original(*args, **kwargs)

    vae.decode = decode

    def restore():
        handle.remove()
        vae.decode = original
        vae.to("cuda")
        transformer.to("cuda")
        torch.cuda.empty_cache()

    return restore


def render(model, inputs, on_step=None):
    """Make one clip. Returns (video frames, audio, sampling rate, details)."""
    from PIL import Image

    torch = model["torch"]
    mode = inputs.get("mode") or "text"
    workflow = WORKFLOW_OF[mode]
    if on_step:
        on_step(0, 0)  # a cancel requested while the job waited takes effect before a model swap
    _use_transformer(model, TRANSFORMER_OF[workflow])
    frames = LENGTHS[str(inputs.get("length") or "5")]
    first = last = None
    extra, pictures, videos, audios = {}, [], [], []
    if workflow == "fl2va":
        first, last = _picture(inputs.get("first")), _picture(inputs.get("last"))
        extra = {key: value for key, value in (("image", first), ("last_image", last)) if value is not None}
        anchor = first or last
    elif workflow == "ref2va":
        pictures, videos, audios = _references(inputs)
        extra = {"references": [*pictures, *videos, *audios]}
        anchor = None
        if pictures:
            image = pictures[0].image
            anchor = image if isinstance(image, Image.Image) else Image.fromarray(image)
        elif videos:
            anchor = Image.fromarray(videos[0].frames[0])
    else:
        anchor = None
    width, height = canvas_size(inputs, anchor)
    final = output_size(inputs, anchor)
    if workflow == "fl2va":
        first = _frame_crop(first, inputs.get("first_crop"), width, height)
        last = _frame_crop(last, inputs.get("last_crop"), width, height)
        extra = {key: value for key, value in (("image", first), ("last_image", last)) if value is not None}
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    quality = QUALITY_ALIASES.get(inputs.get("quality"), inputs.get("quality"))
    quality = quality if quality in STEPS else "turbo"
    if quality == "turbo" and not model["turbo"]:
        quality = "standard"
    turbo = quality == "turbo"
    if model["turbo"] and turbo != model["turbo_on"]:
        set_turbo(model["transformer"], turbo)
        model["turbo_on"] = turbo
    steps = STEPS[quality]
    if workflow == "ref2va":
        prompt = build_reference_prompt(inputs, len(pictures), len(videos), len(audios))
    else:
        prompt = build_prompt(inputs, first=first is not None, last=last is not None, seconds=frames / FPS)
    common = {"width": width, "height": height, "num_frames": frames} if workflow == "ref2va" else {"width": width, "height": height}
    if workflow == "ref2va":
        detail = inputs.get("detail") if inputs.get("detail") in DETAIL else "standard"
        edge, video_edge = DETAIL[detail], VIDEO_DETAIL[detail]
        for pipe in (model["encoders"][workflow], model["pipes"][workflow]):
            if pipe.config.get("reference_image_short_edge") != edge or pipe.config.get("canvas_short_edge") != video_edge:
                pipe.update_components(reference_image_short_edge=edge, canvas_short_edge=video_edge,
                                       canvas_max_pixels=video_edge * round(video_edge * 16 / 9 / 32) * 32)
    reading = time.perf_counter()
    with torch.inference_mode():
        encoded = model["encoders"][workflow](prompt=prompt, **common, **extra,
                                              output=["prompt_embeds", "text_token_tags"])
    embeds = encoded["prompt_embeds"].to("cuda", DTYPE)
    print(f"[worker] prompt read on the processor in {time.perf_counter() - reading:.1f} s "
          f"({embeds.shape[1]} tokens)", flush=True)
    hook = None
    turns = _take_turns(model) if frames * width * height > TAKE_TURNS_ABOVE else None
    if on_step:
        done = [0]

        def count(module, args):  # H3 is guidance-free: one transformer call per step
            done[0] += 1
            on_step(min(done[0], steps), steps)
        hook = model["transformer"].register_forward_pre_hook(count)
    try:
        # H3 counts the final zero of its noise schedule as a step: steps + 1 gives `steps` model calls.
        result = model["pipes"][workflow](
            prompt_embeds=embeds, text_token_tags=encoded["text_token_tags"], num_frames=frames, width=width,
            height=height, num_inference_steps=steps + 1, generator=torch.Generator().manual_seed(seed),
            output=["videos", "audio", "sampling_rate"], **extra)
    finally:
        if hook:
            hook.remove()
        if turns:
            turns()
    details = {"seed": seed, "steps": steps, "quality": quality, "width": width, "height": height,
               "frames": frames, "mode": mode, "prompt": prompt}
    if final:
        how = "flashvsr" if _resolution(inputs) == "1080p (AI upscale)" else "lanczos"
        details.update(rendered_width=width, rendered_height=height, width=final[0], height=final[1], upscaled=how)
    if workflow == "ref2va":
        details.update(reference_detail=detail, reference_picture_edge=edge, reference_video_edge=video_edge)
    return result["videos"][0], result["audio"][0], result["sampling_rate"], details


def _resize_frames(video, width, height):
    """Resize every frame (Lanczos): the simple upscale for resolutions that do not fit on the card."""
    import numpy as np
    from PIL import Image

    frames = video if isinstance(video, list) else list(video)
    out = []
    for frame in frames:
        image = frame if isinstance(frame, Image.Image) else Image.fromarray(
            (np.asarray(frame) * 255).round().clip(0, 255).astype("uint8") if np.asarray(frame).dtype != np.uint8 else np.asarray(frame))
        out.append(image.resize((width, height), Image.LANCZOS))
    return out


def _frame(path, index):
    """One frame of the finished file, as a PIL image (about a second in, past any fade-in)."""
    import av

    with av.open(str(path)) as container:
        last = None
        for number, frame in enumerate(container.decode(video=0)):
            last = frame
            if number >= index:
                break
        return last.to_image()


def generate(model, inputs, job):
    from diffusers.utils.export_utils import encode_video

    torch = model["torch"]
    job.report("Reading the description")
    started = time.perf_counter()
    try:
        _make_clip(model, inputs, job, started, encode_video)
    finally:
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.empty_cache()  # hand cached working memory back between clips, also after a cancel


def _flashvsr(model, video, audio, rate, details, job, encode_video):
    """Enlarge the clip with FlashVSR+ (its own environment, run as a separate process on this card).

    H3's transformer waits in system RAM meanwhile (about 2 s each way), leaving the card to FlashVSR+.
    FlashVSR+ needs sides divisible by 128, so it makes the next size up in the clip's proportions and the
    result is scaled down (Lanczos) to the exact final size. Returns the final frames.
    """
    import subprocess
    import tempfile

    import av

    options, torch = model["options"], model["torch"]
    width, height = details["width"], details["height"]
    big_w, big_h = flashvsr_size(width, height)
    with tempfile.TemporaryDirectory(prefix="h3-flashvsr-") as scratch:
        source, enlarged = os.path.join(scratch, "in.mp4"), os.path.join(scratch, "out.mp4")
        encode_video(video, fps=FPS, output_path=source, audio=audio, audio_sample_rate=rate)
        model["transformer"].to("cpu")
        torch.cuda.empty_cache()
        try:
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            command = [options["flashvsr_python"], "-m", "inference.run_stream", "--input", source, "--output", enlarged,
                       "--height", str(big_h), "--width", str(big_w), "--mode", options.get("flashvsr_mode", "base"),
                       "--attn-kernel", "triton_block_sparse"]
            process = subprocess.Popen(command, cwd=options["flashvsr_dir"], env=env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            begun = time.perf_counter()
            while process.poll() is None:
                try:
                    job.report(f"Upscaling to 1080p with FlashVSR+ ({time.perf_counter() - begun:.0f} s)")
                except BaseException:
                    process.kill()  # a cancel: stop the upscale too
                    raise
                time.sleep(1)
            if process.returncode != 0:
                tail = (process.stderr.read() or "")[-800:]
                raise RuntimeError(f"FlashVSR+ failed (exit {process.returncode}): {tail}")
        finally:
            model["transformer"].to("cuda")
        job.report("Finishing the 1080p picture")
        with av.open(enlarged) as container:
            frames = [frame.to_image() for frame in container.decode(video=0)]
    return _resize_frames([_cover(frame, width, height) for frame in frames], width, height)


def flashvsr_size(width, height):
    """The size FlashVSR+ makes for a final width x height: sides divisible by 128, short side rounded up, the long
    side as close to the final proportions as 128-pixel steps allow (2048 x 1152 for 1920 x 1080)."""
    short, long = min(width, height), max(width, height)
    big_short = -(-short // 128) * 128
    big_long = max(big_short, round(big_short * long / short / 128) * 128)
    return (big_long, big_short) if width >= height else (big_short, big_long)


def _make_clip(model, inputs, job, started, encode_video):
    torch = model["torch"]
    def step(done, total):
        job.report(f"Filming, step {done} of {total}" if total else "Getting the model ready")
    video, audio, rate, details = render(model, inputs, step)
    job.report("Developing the picture and sound")
    path = job.output(f"video-{details['seed']}.mp4", "video/mp4")
    if details.get("upscaled") == "flashvsr":
        video = _flashvsr(model, video, audio, rate, details, job, encode_video)
    elif details.get("upscaled"):
        job.report("Resizing to 1080p")
        video = _resize_frames(video, details["width"], details["height"])
    encode_video(video, fps=FPS, output_path=str(path), audio=audio, audio_sample_rate=rate)
    job.detail(**details, fps=FPS, clip_seconds=round(details["frames"] / FPS, 1))
    job.thumbnail(_frame(path, FPS))
    print(f"[worker] clip {details['width']}x{details['height']} {details['frames']} frames {details['quality']}: "
          f"{time.perf_counter() - started:.1f} s, peak {torch.cuda.max_memory_reserved() / 2**30:.1f} GiB reserved",
          flush=True)
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {details['seed']}")


def cleanup(model):
    """After every clip (also a cancelled one, whose tensors are only released once it has unwound)."""
    model["torch"].cuda.empty_cache()


if __name__ == "__main__":
    serve(load, generate, cleanup=cleanup)
