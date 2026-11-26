"""ACE-Step 1.5: songs with vocals, or instrumentals, from a style description and lyrics."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

LANGUAGES = ("en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru")


class AceStepPreset(WorkerPreset):
    pass


class AceStepRuntime(WorkerRuntime):
    kind: Literal["ace_step"]
    presets: dict[str, AceStepPreset] = Field(min_length=1)


class AceStepPlugin(WorkerPlugin):
    kind = "ace_step"
    title = "ACE-Step"
    description = ("Makes complete songs, with vocals or as instrumentals, from a style description and lyrics. "
                   "ACE-Step 1.5 (MIT) on MLX: a 30 second song takes about 10 seconds.")
    runtime_model = AceStepRuntime
    worker_script = "ace_step_mlx_worker.py"
    max_gpus = 1
    output_kind = "audio"
    # Apple silicon (MLX, turbo, 8 steps), M5 Max, 2026-11-26: 8 s for 30 s, 16-24 s for 60 s, 26-32 s for 120 s.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, when={"length": "30"}, seconds=10, first_seconds=25),
        TimingSpec(preset="mlx", gpu=0, when={"length": "60"}, seconds=20),
        TimingSpec(preset="mlx", gpu=0, when={"length": "120"}, seconds=30),
    )
    inputs: ClassVar[dict[str, InputSpec]] = {
        "style": InputSpec(
            label="Style", kind="text", required=True, max_length=400,
            placeholder="Warm acoustic pop, female vocal, fingerpicked guitar, 96 BPM",
            help="The genre, mood, instruments, voice and tempo, separated by commas."),
        "lyrics": InputSpec(
            label="Lyrics", kind="textarea", max_length=4000,
            placeholder="[Verse]\nMorning light across the quiet street\n\n[Chorus]\nSing it out loud, we're moving on",
            help="Put each part under a tag: [Verse], [Chorus], [Bridge], [Outro]. Leave this empty for an instrumental."),
        "length": InputSpec(label="Length", kind="choice", options=("60", "30", "120"), default="60",
                            help="Seconds of music. Longer songs need more memory."),
        "language": InputSpec(label="Language", kind="choice", options=LANGUAGES, default="en",
                              help="The language the lyrics are sung in.", advanced=True),
        "seed": InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                          help="Reuse a seed to get the same song again. Leave empty for a new one."),
    }
