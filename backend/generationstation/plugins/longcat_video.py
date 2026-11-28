"""LongCat-Video: short video clips from a description, a first picture or an earlier clip, 8-bit with the 8-step fast path."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .video import VideoInfo
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class LongCatVideoPreset(WorkerPreset):
    pass


class LongCatVideoRuntime(WorkerRuntime):
    kind: Literal["longcat_video"]
    presets: dict[str, LongCatVideoPreset] = Field(min_length=1)


LENGTH = InputSpec(
    label="Length", kind="choice", options=("very short", "short", "medium", "long"), default="short",
    option_labels={"very short": "Very short (0.6 seconds)", "short": "Short (1.1 seconds)",
                   "medium": "Medium (2.2 seconds)", "long": "Long (4 seconds)"},
    help="Longer clips take much longer: about 45 seconds, 1.5, 3 and 6 minutes. The long clip needs about 37 GiB of memory.")
SEED = InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                 help="Reuse a seed to get the same clip again. Leave empty for a new one.")
PROMPT = InputSpec(
    label="Description", kind="textarea", required=True, max_length=2000,
    placeholder="A red fox trots through fresh snow in a pine forest, soft morning light, the camera follows it",
    help="Describe the subject, the motion, the setting, the light and the camera.")


class LongCatVideoPlugin(WorkerPlugin):
    kind = "longcat_video"
    title = "LongCat video"
    description = ("Short video clips from a description, a first picture or an earlier clip, 832x480 without sound. LongCat-Video "
                   "(MIT, 13.6B) in 8 bits through MLX with its 8-step fast path. Slow: under a minute for the "
                   "shortest clip and about six for four seconds.")
    runtime_model = LongCatVideoRuntime
    worker_script = "longcat_mlx_worker.py"
    max_gpus = 1
    output_kind = "video"
    make_label = "Make a clip"
    result_noun = "clip"
    # Apple silicon (MLX, 8-bit, 8 steps), 832x480, 15 fps, M5 Max (2026-11-26), including the model load, one clip at a
    # time on an idle machine. Measured: very short 43 s, short 80 s. Medium and long are scaled from an earlier
    # run (243 s and 549 s for 33 and 61 frames, taken while other work shared the machine).
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="q8", gpu=0, when={"length": "very short"}, seconds=43),
        TimingSpec(preset="q8", gpu=0, when={"length": "short"}, seconds=80),
        TimingSpec(preset="q8", gpu=0, when={"length": "medium"}, seconds=170),
        TimingSpec(preset="q8", gpu=0, when={"length": "long"}, seconds=380),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "text": ModeSpec(label="From a description", help="LongCat imagines the clip from your words.",
                         inputs={"prompt": PROMPT, "length": LENGTH, "seed": SEED}),
        "image": ModeSpec(
            label="From a picture", help="The picture becomes the first frame; the description says what moves. The clip is cropped to 832x480.",
            inputs={"image": InputSpec(label="First frame", kind="files", accept=("image",), required=True, max_count=1,
                                       help="The clip starts from this picture."),
                    "prompt": PROMPT, "length": LENGTH, "seed": SEED}),
        "continue": ModeSpec(
            label="Continue a clip", help="LongCat carries on from the last frames of a clip, and the result is the end of that clip plus the new part. "
                                          "Some continuations show artifacts at the join: try another seed.",
            inputs={"source": InputSpec(label="Clip to continue", kind="files", accept=("video",), required=True, max_count=1,
                                        help="The new part continues from the last half second of this clip."),
                    "prompt": PROMPT, "length": LENGTH, "seed": SEED}),
    }
    video: ClassVar[VideoInfo] = VideoInfo(
        guidance=("Describe the subject, the motion, the setting, the light and the camera. Clips are silent, 832x480, and slow to make. "
                  "A first picture or an earlier clip can start the next one; continuations sometimes show artifacts at the join, so try another seed."),
        sound="none", create="text", picture="image", extend="continue",
        seconds={"very short": 0.6, "short": 1.1, "medium": 2.2, "long": 4.1},
        roles={mode: {"prompt": "prompt", "length": "length", "seed": "seed", **extra} for mode, extra in
               (("text", {}), ("image", {"first": "image"}), ("continue", {"source": "source"}))})
