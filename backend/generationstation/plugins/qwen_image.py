"""Qwen Image 2.1: makes a picture from a description."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, SettingSpec, TimingSpec
from .images import ImageInfo
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
        # Apple silicon (mflux, the model stays loaded, the text encoder is released after each description), 1344x768 on an M5 Max
        # with other models running: Turbo 17 s, Z-Image 14 s, the full 2.1 about 4.3 s per step, Qwen-Image 2512 about 8 s per step.
        TimingSpec(preset="mlx", gpu=0, seconds=17),
        TimingSpec(preset="qwen21", gpu=0, seconds=130),
        TimingSpec(preset="zimage", gpu=0, seconds=14),
        TimingSpec(preset="qwen2512", gpu=0, seconds=160, note="about 8 s per step; peaks near 35 GiB"),
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
            label="Shape", kind="choice", options=("square", "portrait", "landscape", "wide", "custom", "match picture"), default="square",
            option_labels={"custom": "Custom size", "match picture": "Match the starting picture"},
            help="Square 1024x1024, portrait 768x1152, landscape 1152x768, wide 1344x768. Custom lets you set the width and "
                 "height (bigger pictures take longer and need more memory). 'Match the starting picture' keeps its size."),
        "width": InputSpec(
            label="Width", kind="int", minimum=256, maximum=2048, default=1024, show_when={"size": "custom"},
            help="In pixels, 256 to 2048. Rounded down to a multiple of 16."),
        "height": InputSpec(
            label="Height", kind="int", minimum=256, maximum=2048, default=1024, show_when={"size": "custom"},
            help="In pixels, 256 to 2048. Rounded down to a multiple of 16."),
        "picture": InputSpec(
            label="Start from a picture", kind="files", accept=("image",), max_count=1,
            help="Draws a new picture that begins from this one (a variation or a restyle) instead of from nothing. It does "
                 "not follow instructions like \"make the coat blue\"; describe the whole picture you want."),
        "strength": InputSpec(
            label="How closely it follows the picture", kind="int", minimum=5, maximum=95, placeholder="40",
            help="Percent (40 if empty). Low: only the rough layout and colours of your picture stay. High: it stays close to it. "
                 "Used only with a starting picture."),
        "quality": InputSpec(
            label="Quality", kind="choice", options=("quick", "best"), default="quick",
            help="'quick' takes a few seconds. 'best' takes 15-45 s and draws finer detail and small lettering. "
                 "Turbo models have one setting and ignore this."),
        "negative_prompt": InputSpec(
            label="Avoid", kind="text", max_length=400, placeholder="blurry, extra fingers",
            help="Things to keep out of the picture. Used only at 'best' quality.", advanced=True),
        "steps": InputSpec(
            label="Steps", kind="int", minimum=1, maximum=100,
            help="How many painting steps. Leave empty for the model's own number (8 for the Turbo models, 20 to 30 for "
                 "the full ones). More steps rarely help a Turbo model.", advanced=True),
        "seed": InputSpec(
            label="Seed", kind="seed", minimum=0, maximum=2**31 - 1,
            help="Leave empty for a new picture each time. Reuse a seed to get the same picture again.",
            advanced=True),
    }

    image: ClassVar[ImageInfo] = ImageInfo(
        guidance=("Describe the subject, setting, style and light. Put any words that should appear in the picture in quotes: "
                  "these models draw legible lettering."),
        create="", roles={"": {"prompt": "prompt", "shape": "size", "width": "width", "height": "height", "start": "picture", "strength": "strength",
                               "quality": "quality", "negative": "negative_prompt", "steps": "steps", "seed": "seed"}})

    @staticmethod
    def _mflux(runtime) -> bool:
        return "mflux" in (runtime.worker_script or "")

    def mode_inputs(self, mode, runtime=None):
        """The Apple-silicon (mflux) models make one quality per preset, so they have no Quality field; a model whose presets
        use no negative prompt has no Avoid field. Custom sizes, a starting picture and the step count are what the mflux
        worker does; the Windows worker has only the four shapes."""
        inputs = super().mode_inputs(mode, runtime)
        if runtime is None:
            return inputs
        drop = set()
        if self._mflux(runtime):
            drop.add("quality")
            if not any(preset.options.get("negative") for preset in runtime.presets.values()):
                drop.add("negative_prompt")
            return {key: spec for key, spec in inputs.items() if key not in drop}
        drop |= {"width", "height", "picture", "strength", "steps"}
        shapes = inputs["size"].model_copy(update={"options": tuple(o for o in inputs["size"].options if o not in {"custom", "match picture"}),
                                                   "help": "Square 1024x1024, portrait 768x1152, landscape 1152x768, wide 1344x768."})
        return {key: (shapes if key == "size" else spec) for key, spec in inputs.items() if key not in drop}

    def check_inputs(self, mode, values, files):
        if values.get("size") == "match picture" and not files.get("picture"):
            return ["Add a starting picture to match its size, or choose another shape."]
        return []

    def estimate(self, runtime, preset, values, gpus):
        ram, vram = super().estimate(runtime, preset, values, gpus)
        if values.get("text_encoder_device") == "cuda":
            return max(ram - TEXT_ENCODER_GIB, 4), {gpu: need + TEXT_ENCODER_GIB for gpu, need in vram.items()}
        return ram, vram
