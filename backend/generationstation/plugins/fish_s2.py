"""Fish Audio S2 Pro: expressive speech directed with [tags] in the text, in a cloned or model-chosen voice."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime


class FishS2Preset(WorkerPreset):
    pass


class FishS2Runtime(WorkerRuntime):
    kind: Literal["fish_s2"]
    presets: dict[str, FishS2Preset] = Field(min_length=1)


class FishS2Plugin(WorkerPlugin):
    kind = "fish_s2"
    title = "Fish Audio S2 Pro"
    description = ("Speech you direct with cues in the text, such as [whisper] or [laughing], in a voice cloned from "
                   "a short sample or chosen by the model. Fish Audio Research License: research and personal use "
                   "only, not for a company's own work.")
    runtime_model = FishS2Runtime
    worker_script = "fish_s2_mlx_worker.py"
    max_gpus = 1
    output_kind = "audio"
    make_label = "Make speech"
    result_noun = "recording"
    # Apple silicon (MLX, 8-bit), 2026-11-26: 4 s of speech in 10 s, a cloned 2 s line in 7 s (about 0.6x real time).
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(preset="mlx", gpu=0, seconds=10, note="for a sentence or two"),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "speak": ModeSpec(
            label="Speak a text",
            help="Write what to say with directions in brackets. Add a voice sample to speak in that voice. Only "
                 "clone voices you have permission to use.",
            inputs={
                "prompt": InputSpec(
                    label="What to say", kind="textarea", required=True, max_length=3000,
                    placeholder="[whisper] Don't wake the baby. [pause] She just fell asleep.",
                    help="The words to speak. Put a cue in square brackets where it should happen, in plain words: "
                         "[whisper], [laughing], [pause], [excited], [sad]. Any short description works."),
                "sample": InputSpec(
                    label="Voice sample", kind="files", accept=("audio",), max_count=1,
                    help="Optional: 5-15 seconds of one person speaking clearly, without music."),
                "sample_text": InputSpec(
                    label="What the sample says", kind="text", max_length=1000,
                    help="The exact words in the sample. Left empty, they are written down for you."),
                "seed": InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                                  help="Reuse a seed to get the same take again. Leave empty for a fresh one."),
            }),
    }
