"""Wan 2.2 (TI2V 5B): short video clips from a description or a first picture."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class WanVideoPreset(WorkerPreset):
    pass


class WanVideoRuntime(WorkerRuntime):
    kind: Literal["wan_video"]
    presets: dict[str, WanVideoPreset] = Field(min_length=1)


SHAPE = InputSpec(label="Shape", kind="choice", options=("landscape", "portrait", "square"), default="landscape",
                  help="Landscape 832x480, portrait 480x832, square 640x640.")
LENGTH = InputSpec(label="Length", kind="choice", options=("short", "very short"), default="short",
                   help="Short is 1.4 seconds, very short 0.7 seconds. Longer clips need more memory than this Mac "
                        "offers.")
NEGATIVE = InputSpec(label="Avoid", kind="text", max_length=400, advanced=True,
                     help="Things to keep out of the clip. Empty uses Wan's own default list.")
SEED = InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                 help="Reuse a seed to get the same clip again. Leave empty for a new one.")
PROMPT = InputSpec(
    label="Description", kind="textarea", required=True, max_length=2000,
    placeholder="A red fox trots through fresh snow in a pine forest, soft morning light, the camera follows it",
    help="Describe the subject, the motion, the setting, the light and the camera.")


class WanVideoPlugin(WorkerPlugin):
    kind = "wan_video"
    title = "Wan 2.2 video"
    description = ("Short video clips from a description or a first picture. Wan 2.2 TI2V 5B (Apache-2.0) in 8 bits "
                   "through MLX: 832x480 clips of up to 1.4 seconds.")
    runtime_model = WanVideoRuntime
    worker_script = "wan_mlx_worker.py"
    max_gpus = 1
    output_kind = "video"
    make_label = "Make a clip"
    result_noun = "clip"
    # Apple silicon (MLX, 8-bit), 832x480, 33 frames, 20 steps, M5 Max (2026-11-26): about 90-100 s.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, when={"length": "short"}, seconds=100),
        TimingSpec(preset="mlx", gpu=0, when={"length": "very short"}, seconds=60),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "text": ModeSpec(label="From a description", help="Wan imagines the clip from your words.",
                         inputs={"prompt": PROMPT, "shape": SHAPE, "length": LENGTH, "negative_prompt": NEGATIVE,
                                 "seed": SEED}),
        "image": ModeSpec(
            label="From a picture", help="The picture becomes the first frame; the description says what moves.",
            inputs={"image": InputSpec(label="First frame", kind="files", accept=("image",), required=True,
                                       max_count=1, help="The clip starts from this picture. Its shape is set "
                                                         "by the Shape choice below, so use a matching picture."),
                    "prompt": PROMPT, "shape": SHAPE, "length": LENGTH, "negative_prompt": NEGATIVE, "seed": SEED}),
    }
