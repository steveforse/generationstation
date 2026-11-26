"""MiniMax H3 on Apple silicon (antirez/h3.c): short video clips with sound, from a description or from pictures."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class H3VideoPreset(WorkerPreset):
    pass


class H3VideoRuntime(WorkerRuntime):
    kind: Literal["h3_video"]
    presets: dict[str, H3VideoPreset] = Field(min_length=1)


SHAPE = InputSpec(label="Shape", kind="choice", options=("landscape 16:9", "portrait 9:16", "square 1:1"),
                  default="landscape 16:9", help="Landscape for screens, portrait 9:16 for phones, or square.")
RESOLUTION = InputSpec(label="Resolution", kind="choice", options=("480p", "540p", "360p", "240p"), default="480p",
                       help="The short edge of the clip. Lower resolutions are much faster.")
LENGTH = InputSpec(label="Length", kind="choice", options=("5", "3", "10"), default="5", help="Seconds.")
QUALITY = InputSpec(label="Quality", kind="choice", options=("draft", "standard"), default="draft",
                    help="Draft is 4 steps, for trying ideas. Standard is 20 steps: finer detail and steadier motion, "
                         "several times slower.")
SEED = InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                 help="Reuse a seed to get the same clip again. Leave empty for a new one.")
PROMPT = InputSpec(
    label="Description", kind="textarea", required=True, max_length=3000,
    placeholder="A red fox trots through a snowy pine forest at dawn, stops, looks at the camera and bounds away.",
    help="Describe what is seen and what happens, in order, and how the camera moves. For speech, write who speaks "
         "and put their words in quotes: She says: \"Wait for me by the clock.\"")


class H3VideoPlugin(WorkerPlugin):
    kind = "h3_video"
    title = "MiniMax H3 video"
    description = ("Short video clips with matching sound from a description or from a first and last picture, on "
                   "MiniMax H3 through the h3.c Metal engine. The H3 licence excludes the US, EU, UK and South Korea: "
                   "personal use only.")
    runtime_model = H3VideoRuntime
    worker_script = "h3_mlx_worker.py"
    max_gpus = 1
    output_kind = "video"
    make_label = "Make a clip"
    result_noun = "clip"
    # Apple silicon (h3.c, SSD streaming), M5 Max, 2026-11-26.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, when={"quality": "draft", "length": "5", "resolution": "480p"}, seconds=200),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "draft"}, seconds=120),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "standard", "length": "5", "resolution": "480p"}, seconds=990),
        TimingSpec(preset="mlx", gpu=0, when={"quality": "standard"}, seconds=600),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "text": ModeSpec(label="From a description", help="Write what happens and H3 films it, with sound.",
                         inputs={"prompt": PROMPT, "shape": SHAPE, "resolution": RESOLUTION, "length": LENGTH,
                                 "quality": QUALITY, "seed": SEED}),
        "frames": ModeSpec(
            label="From pictures", help="Start from a picture, end on one, or both: H3 makes the motion in between.",
            inputs={"first": InputSpec(label="First frame", kind="files", accept=("image",), max_count=1,
                                       help="The picture the clip starts from. Leave empty to only end on the last frame."),
                    "last": InputSpec(label="Last frame", kind="files", accept=("image",), max_count=1,
                                      help="The picture the clip ends on. Leave empty to only start from the first frame."),
                    "prompt": PROMPT, "shape": SHAPE, "resolution": RESOLUTION, "length": LENGTH, "quality": QUALITY,
                    "seed": SEED}),
    }

    def check_inputs(self, mode, values, files):
        if mode == "frames" and not (files.get("first") or files.get("last")):
            return ["Add a first frame, a last frame, or both."]
        return []
