"""Breeze TTS 2 (BreezeBlue): English and Chinese speech in a described or cloned voice."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class BreezeTTSPreset(WorkerPreset):
    pass


class BreezeTTSRuntime(WorkerRuntime):
    kind: Literal["breeze_tts"]
    presets: dict[str, BreezeTTSPreset] = Field(min_length=1)


SEED = InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                 help="Reuse a seed to get the same take again. Leave empty for a fresh one.")
TEXT = InputSpec(
    label="What to say", kind="textarea", required=True, max_length=3000,
    placeholder="Good evening, and welcome aboard. (laugh) Mind the gap!",
    help="English or Chinese. Sounds in round brackets work in English: (laugh), (sigh), (cough), (clears throat). "
         "In Chinese use [笑].")


class BreezeTTSPlugin(WorkerPlugin):
    kind = "breeze_tts"
    title = "Breeze TTS 2"
    description = ("English and Chinese speech in a voice described in words or cloned from a short sample. "
                   "BreezeBlue's licence allows research and personal use only, not a company's own work.")
    runtime_model = BreezeTTSRuntime
    worker_script = "breeze_tts_mlx_worker.py"
    max_gpus = 1
    output_kind = "audio"
    make_label = "Make speech"
    result_noun = "recording"
    # Apple silicon (MLX, 8-bit), 2026-11-26: 2 s of speech in about 10 s on a warm start while other jobs ran.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, seconds=8, note="for a sentence or two"),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "design": ModeSpec(
            label="Describe a voice",
            help="Describe who is speaking and how, and the model invents a voice to match.",
            inputs={
                "prompt": TEXT,
                "voice": InputSpec(
                    label="Voice", kind="text", required=True, max_length=300,
                    placeholder="A warm middle-aged woman, calm and clear",
                    help="Age, gender, tone and manner in plain words."),
                "seed": SEED,
            }),
        "clone": ModeSpec(
            label="Clone a voice",
            help="Speak the text in the voice of a short sample. Only clone voices you have permission to use.",
            inputs={
                "prompt": TEXT,
                "sample": InputSpec(
                    label="Voice sample", kind="files", accept=("audio",), required=True, max_count=1,
                    help="5-15 seconds of one person speaking clearly, without music."),
                "sample_text": InputSpec(
                    label="What the sample says", kind="text", max_length=1000,
                    help="The exact words in the sample. Left empty, they are written down for you."),
                "voice": InputSpec(
                    label="Direction", kind="text", max_length=300, advanced=True,
                    help="Optional: how to say it, for example \"quietly, with a smile\"."),
                "seed": SEED,
            }),
    }
