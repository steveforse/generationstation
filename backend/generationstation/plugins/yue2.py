"""YuE2: makes a full song (vocals and instruments) from lyrics and a style description."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, SettingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class YuE2Preset(WorkerPreset):
    pass


class YuE2Runtime(WorkerRuntime):
    kind: Literal["yue2"]
    presets: dict[str, YuE2Preset] = Field(min_length=1)


LYRICS_HELP = ("Put each part on its own lines under a tag: [Verse], [Pre-Chorus], [Chorus], [Bridge], "
               "[Intro], [Interlude], [Outro]. Leave a blank line between parts.")


class YuE2Plugin(WorkerPlugin):
    kind = "yue2"
    title = "YuE2"
    runtime_model = YuE2Runtime
    worker_script = "yue2_worker.py"
    max_gpus = 1
    output_kind = "audio"
    settings: ClassVar[dict[str, SettingSpec]] = {
        "memory_budget_gib": SettingSpec(
            label="VRAM limit", target="memory_budget_gib", kind="int", minimum=12, maximum=32, unit="GiB",
            help="Most YuE2 may use on its card, including a 2 GiB cushion. Songs peak at about 11-14 GiB."),
        "quantization": SettingSpec(
            label="Precision", target="quantization", kind="choice", options=("none", "fp8"),
            help="fp8 uses less VRAM at some cost in quality. 'none' is full precision."),
    }
    inputs: ClassVar[dict[str, InputSpec]] = {
        "style": InputSpec(
            label="Style", kind="text", required=True, max_length=400,
            placeholder="Upbeat indie pop, female vocals, acoustic guitar, warm, summery",
            help="Describe the genre, mood, instruments and voice, separated by commas."),
        "lyrics": InputSpec(
            label="Lyrics", kind="textarea", required=True, max_length=8000,
            placeholder="[Verse]\nFirst line of the song\nSecond line\n\n[Chorus]\nThe part everyone sings",
            help=LYRICS_HELP),
        "mode": InputSpec(
            label="Melody planning", kind="choice", options=("full", "melody", "off"), default="full",
            help="'full' plans melody and chords first (best). 'off' is faster but less structured.",
            advanced=True),
        "seed": InputSpec(
            label="Seed", kind="seed", minimum=0, maximum=2**31 - 1,
            help="Leave empty for a new song each time. Reuse a seed to get the same song again.",
            advanced=True),
    }
