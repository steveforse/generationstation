"""FastMetal-QAD: short video clips from a description, distilled Wan models that run in about 3 steps on MLX."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class FastMetalPreset(WorkerPreset):
    pass


class FastMetalRuntime(WorkerRuntime):
    kind: Literal["fastmetal_video"]
    presets: dict[str, FastMetalPreset] = Field(min_length=1)


# Measured on an M5 Max (2026-11-26), warm prompt, whole process including Python start-up:
#   5B 1280x704:  81 frames 72 s (fast 41 s), 121 frames 121 s.  14B 832x480: 81 frames 338 s (fast 135 s).
# Other lengths are scaled from those; a new description adds 5-25 s for the text encoder.
_SECONDS = {
    "5b": {"full": {"short": 50, "medium": 75, "long": 125}, "fast": {"short": 30, "medium": 42, "long": 65}},
    "14b": {"full": {"short": 150, "medium": 220, "long": 340}, "fast": {"short": 70, "medium": 95, "long": 140}},
}


class FastMetalVideoPlugin(WorkerPlugin):
    kind = "fastmetal_video"
    title = "FastMetal video"
    description = ("Short video clips from a description (no first picture, no sound). FastMetal-QAD (Apache-2.0) are "
                   "Wan models distilled to 3 steps and quantised to 8 bits for MLX: the 5B makes up to 5 seconds at "
                   "1280x704, the 14B up to 5 seconds at 832x480.")
    runtime_model = FastMetalRuntime
    worker_script = "fastmetal_mlx_worker.py"
    max_gpus = 1
    output_kind = "video"
    make_label = "Make a clip"
    result_noun = "clip"
    inputs: ClassVar[dict[str, InputSpec]] = {
        "prompt": InputSpec(
            label="Description", kind="textarea", required=True, max_length=2000,
            placeholder="A red fox trots through fresh snow in a pine forest, soft morning light, the camera follows it",
            help="Describe the subject, the motion, the setting, the light and the camera."),
        "shape": InputSpec(label="Shape", kind="choice", options=("landscape", "portrait"), default="landscape",
                           help="Landscape is wide, portrait is tall. The size follows the model: 1280x704 for the 5B, "
                                "832x480 for the 14B."),
        "length": InputSpec(label="Length", kind="choice", options=("short", "medium", "long"), default="medium",
                            option_labels={"short": "Short (about 2 seconds)", "medium": "Medium (about 3 seconds)",
                                           "long": "Long (about 5 seconds)"},
                            help="Longer clips take longer."),
        "speed": InputSpec(label="Speed", kind="choice", options=("full", "fast"), default="full",
                           option_labels={"full": "Full quality", "fast": "Faster (makes half the frames, then fills in the rest)"},
                           help="Faster takes about 40-60% of the time; fast motion can look a little smoother than it should."),
        "seed": InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                          help="Reuse a seed to get the same clip again. Leave empty for a new one."),
    }
    timings: ClassVar[tuple[TimingSpec, ...]] = tuple(
        TimingSpec(preset=preset, gpu=0, when={"speed": speed, "length": length}, seconds=seconds)
        for preset, speeds in _SECONDS.items() for speed, lengths in speeds.items() for length, seconds in lengths.items())
