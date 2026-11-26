"""MiniMax Music 3: songs with vocals, or instrumentals, from a style description and lyrics."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class MiniMaxMusicPreset(WorkerPreset):
    pass


class MiniMaxMusicRuntime(WorkerRuntime):
    kind: Literal["minimax_music"]
    presets: dict[str, MiniMaxMusicPreset] = Field(min_length=1)


class MiniMaxMusicPlugin(WorkerPlugin):
    kind = "minimax_music"
    title = "MiniMax Music 3"
    description = ("Makes complete songs, with vocals or as instrumentals, from a style description and lyrics. "
                   "MiniMax Music 3 in 8 bits on MLX, up to about five minutes.")
    runtime_model = MiniMaxMusicRuntime
    worker_script = "minimax_music_mlx_worker.py"
    max_gpus = 1
    output_kind = "audio"
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, seconds=70, note="for about 30 seconds of music; longer songs take longer"),
    )
    inputs: ClassVar[dict[str, InputSpec]] = {
        "style": InputSpec(
            label="Style", kind="text", required=True, max_length=600,
            placeholder="Warm acoustic pop, female vocal, fingerpicked guitar, 96 BPM",
            help="The genre, mood, instruments, voice and tempo, separated by commas."),
        "lyrics": InputSpec(
            label="Lyrics", kind="textarea", max_length=4000,
            placeholder="[Verse]\nMorning light across the quiet street\n\n[Chorus]\nSing it out loud, we're moving on",
            help="Put each part under a tag: [Verse], [Chorus], [Bridge], [Outro]. Leave this empty for an instrumental."),
        "length": InputSpec(label="Length", kind="choice", options=("30", "60", "120", "180"), default="60",
                            help="The most seconds of music to make; the song may end sooner."),
        "seed": InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                          help="Reuse a seed to get the same song again. Leave empty for a new one."),
    }
