"""LTX-2.5: short video clips with sound from a description or a first picture."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class LtxVideoPreset(WorkerPreset):
    pass


class LtxVideoRuntime(WorkerRuntime):
    kind: Literal["ltx_video"]
    presets: dict[str, LtxVideoPreset] = Field(min_length=1)


SHAPE = InputSpec(label="Shape", kind="choice", options=("landscape", "portrait", "square"), default="landscape",
                  help="Landscape is wide, portrait is tall.")
QUALITY = InputSpec(label="Detail", kind="choice", options=("quick", "sharp"), default="quick",
                    option_labels={"quick": "Quick (about 700 pixels wide)", "sharp": "Sharp (about 1280 pixels wide)"},
                    help="Quick takes about a minute for a 4 second clip. Sharp is about 2.5 times slower.")
LENGTH = InputSpec(label="Length", kind="choice", options=("2 seconds", "4 seconds", "5 seconds"), default="4 seconds",
                   help="Longer clips take longer. The clip comes with sound.")
SEED = InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                 help="Reuse a seed to get the same clip again. Leave empty for a new one.")
PROMPT = InputSpec(
    label="Description", kind="textarea", required=True, max_length=2000,
    placeholder="A red fox trots through fresh snow in a pine forest, soft morning light, birds singing",
    help="Describe the subject, the motion, the setting, the light, the camera and what it sounds like.")


class LtxVideoPlugin(WorkerPlugin):
    kind = "ltx_video"
    title = "LTX-2.5 video"
    description = ("Short video clips with sound from a description or a first picture. LTX-2.5 (4-bit, distilled) "
                   "through MLX: up to 5 seconds at 1280x704. Personal use only: its licence needs a paid licence "
                   "for work above US$10M revenue.")
    runtime_model = LtxVideoRuntime
    worker_script = "ltx_mlx_worker.py"
    max_gpus = 1
    output_kind = "video"
    make_label = "Make a clip"
    result_noun = "clip"
    # Apple silicon (MLX, 4-bit distilled, 24 fps), M5 Max (2026-11-26), including the model load. Measured: quick 49
    # frames 28 s, 97 frames 53 s; sharp 97 frames 147 s. The other lengths are scaled from those.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, when={"quality": "quick", "length": "2 seconds"}, seconds=30),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "quick", "length": "4 seconds"}, seconds=55),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "quick", "length": "5 seconds"}, seconds=70),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "sharp", "length": "2 seconds"}, seconds=80),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "sharp", "length": "4 seconds"}, seconds=150),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "sharp", "length": "5 seconds"}, seconds=190),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "text": ModeSpec(label="From a description", help="LTX imagines the clip and its sound from your words.",
                         inputs={"prompt": PROMPT, "shape": SHAPE, "quality": QUALITY, "length": LENGTH, "seed": SEED}),
        "image": ModeSpec(
            label="From a picture", help="The picture becomes the first frame; the description says what moves.",
            inputs={"image": InputSpec(label="First frame", kind="files", accept=("image",), required=True,
                                       max_count=1, help="The clip starts from this picture. Use one with the "
                                                         "shape you chose below."),
                    "prompt": PROMPT, "shape": SHAPE, "quality": QUALITY, "length": LENGTH, "seed": SEED}),
    }
