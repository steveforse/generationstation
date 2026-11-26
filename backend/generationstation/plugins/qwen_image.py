"""Qwen Image 2.1: makes a picture from a description."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, SettingSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

# The text encoder (Qwen3-VL 8B, BF16) when it is kept on the card instead of in system RAM.
TEXT_ENCODER_GIB = 16


class QwenImagePreset(WorkerPreset):
    pass


class QwenImageRuntime(WorkerRuntime):
    kind: Literal["qwen_image"]
    presets: dict[str, QwenImagePreset] = Field(min_length=1)


class QwenImagePlugin(WorkerPlugin):
    kind = "qwen_image"
    title = "Qwen Image"
    description = "Makes pictures from a written description, including legible lettering on signs and posters."
    runtime_model = QwenImageRuntime
    worker_script = "qwen_image_worker.py"
    max_gpus = 1
    output_kind = "image"
    # 1024x1024 with Speed-up on, after warm-up (2026-11-14/15). Turbo has one quality.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="turbo", gpu=0, seconds=2),
        TimingSpec(preset="turbo", gpu=1, seconds=5.5),
        # Apple silicon (mflux, one process per picture), 1024x1024 on an M5 Max: 17-23 s including process start.
        TimingSpec(preset="mlx", gpu=0, seconds=20),
        TimingSpec(preset="qwen21", gpu=0, seconds=100),
        TimingSpec(preset="zimage", gpu=0, seconds=18),
        TimingSpec(preset="qwen2512", gpu=0, seconds=270, note="needs about 37 GiB while it runs"),
        TimingSpec(when={"quality": "quick"}, gpu=0, seconds=2),
        TimingSpec(when={"quality": "best"}, gpu=0, seconds=15, first_seconds=20),
        TimingSpec(when={"quality": "quick"}, gpu=1, seconds=3.6),
        TimingSpec(when={"quality": "best"}, gpu=1, seconds=42),
    )
    settings: ClassVar[dict[str, SettingSpec]] = {
        "compile": SettingSpec(
            label="Speed-up", target="compile", kind="bool",
            help="Makes each picture 15-40% faster. The first picture at each quality and shape after a start "
                 "is slower (10-90 s) while it prepares."),
        "text_encoder_device": SettingSpec(
            label="Prompt reader", target="text_encoder_device", kind="choice", options=("cpu", "cuda"),
            option_labels={"cpu": "CPU (system RAM)", "cuda": "GPU"},
            help="'cpu' keeps the part that reads the description in system RAM (about half a second per "
                 "picture, and 16 GiB more room on the card). 'cuda' puts it on the card."),
    }
    inputs: ClassVar[dict[str, InputSpec]] = {
        "prompt": InputSpec(
            label="Description", kind="textarea", required=True, max_length=2000,
            placeholder="A cozy bookshop on a rainy evening, warm light through the window, "
                        "a chalkboard sign reading \"Open Late\"",
            help="Describe the subject, setting, style and light. Put any words that should appear in the "
                 "picture in quotes."),
        "size": InputSpec(
            label="Shape", kind="choice", options=("square", "portrait", "landscape", "wide"), default="square",
            help="Square 1024x1024, portrait 768x1152, landscape 1152x768, wide 1344x768."),
        "quality": InputSpec(
            label="Quality", kind="choice", options=("quick", "best"), default="quick",
            help="'quick' takes a few seconds. 'best' takes 15-45 s and draws finer detail and small lettering. "
                 "Turbo models have one setting and ignore this."),
        "negative_prompt": InputSpec(
            label="Avoid", kind="text", max_length=400, placeholder="blurry, extra fingers",
            help="Things to keep out of the picture. Used only at 'best' quality.", advanced=True),
        "seed": InputSpec(
            label="Seed", kind="seed", minimum=0, maximum=2**31 - 1,
            help="Leave empty for a new picture each time. Reuse a seed to get the same picture again.",
            advanced=True),
    }

    def estimate(self, runtime, preset, values, gpus):
        ram, vram = super().estimate(runtime, preset, values, gpus)
        if values.get("text_encoder_device") == "cuda":
            return max(ram - TEXT_ENCODER_GIB, 4), {gpu: need + TEXT_ENCODER_GIB for gpu, need in vram.items()}
        return ram, vram
