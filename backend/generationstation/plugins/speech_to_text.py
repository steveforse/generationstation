"""Speech to text: a recording becomes a transcript. Qwen3-ASR, Whisper, Parakeet and Nemotron through mlx-audio on Apple silicon."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, TimingSpec
from .transcribe import TranscribeInfo
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

LANGUAGES = ("English", "Spanish", "French", "German", "Italian", "Portuguese", "Dutch", "Polish", "Russian", "Japanese", "Korean", "Chinese",
             "Arabic", "Hindi", "Turkish", "Vietnamese", "Swedish", "Czech", "Greek")

RECORDING = InputSpec(
    label="Recording", kind="files", accept=("audio", "video"), max_count=1, required=True,
    help="An audio or video file. Only its sound is used. Everything stays on this computer.")
LANGUAGE = InputSpec(
    label="Language", kind="choice", options=("auto", *LANGUAGES), default="auto", option_labels={"auto": "Detect it"},
    help="The language spoken. Detecting it works for most recordings; name it when the start is quiet or mixes languages.")
TERMS = InputSpec(
    label="Words to expect", kind="textarea", max_length=500, placeholder="Zephyrine, Priya Raman, Q3 roadmap",
    help="Optional: names, product names and jargon that come up, separated by commas, so they are spelled right.")
SPEAKERS = InputSpec(
    label="Who spoke", kind="choice", options=("no", "yes"), default="no", option_labels={"no": "Just the words", "yes": "Label the speakers"},
    help="Labels each line Speaker 1, Speaker 2 and so on. It takes longer, and the labels are only as good as the voices are different.")
SPLIT = InputSpec(
    label="How many speakers", kind="choice", options=("fewer", "usual", "more"), default="usual", advanced=True, show_when={"speakers": "yes"},
    option_labels={"fewer": "Fewer (similar voices count as one)", "usual": "Usual", "more": "More (tells similar voices apart)"},
    help="The speakers are found by how voices sound. If two people come out as one, choose More; if one person is split into several, choose Fewer.")


class SpeechToTextPreset(WorkerPreset):
    pass


class SpeechToTextRuntime(WorkerRuntime):
    presets: dict[str, SpeechToTextPreset] = Field(min_length=1)


class SpeechToTextPlugin(WorkerPlugin):
    """The shared form and worker; each model is a subclass that names itself and takes the fields it has."""

    worker_script = "transcribe_mlx_worker.py"
    max_gpus = 1
    output_kind = "document"
    make_label = "Transcribe"
    result_noun = "transcript"
    transcribe: ClassVar[TranscribeInfo]

    def mode_inputs(self, mode, runtime=None):
        """Who spoke needs the speaker detection of the meeting notes, which a preset sets up."""
        inputs = super().mode_inputs(mode, runtime)
        if runtime is not None and not any("segmentation_model" in preset.options for preset in runtime.presets.values()):
            return {key: spec for key, spec in inputs.items() if key not in ("speakers", "split")}
        return inputs


def roles_of(fields):
    return {"": {role: role for role in fields if role != "split"}}  # "split" is a setting of the speaker step, not carried between models


class Qwen3AsrRuntime(SpeechToTextRuntime):
    kind: Literal["qwen3_asr"]


class Qwen3AsrPlugin(SpeechToTextPlugin):
    kind = "qwen3_asr"
    title = "Qwen3-ASR"
    description = "Writes down speech in 30 languages, in parts of up to 30 seconds with times. Qwen3-ASR 1.7B (Apache-2.0) in 8 bits through MLX."
    runtime_model = Qwen3AsrRuntime
    inputs: ClassVar[dict[str, InputSpec]] = {"recording": RECORDING, "language": LANGUAGE, "terms": TERMS, "speakers": SPEAKERS, "split": SPLIT}
    transcribe = TranscribeInfo(
        guidance="Takes names and terms you give it. The transcript comes in parts of up to 30 seconds, each with its time.", times="lines", speakers="turns",
        checked_minutes=56, roles=roles_of(inputs))
    # 2026-11-27, M5 Max, one clip after the other with the model loaded: 17 minutes of speech in 21 s, 56 minutes in 80 s (3.9 GiB at the peak).
    timings: ClassVar[tuple[TimingSpec, ...]] = (TimingSpec(when={}, preset=None, gpu=0, seconds=21, note="for 17 minutes of speech"),)


class WhisperRuntime(SpeechToTextRuntime):
    kind: Literal["whisper_asr"]


class WhisperPlugin(SpeechToTextPlugin):
    kind = "whisper_asr"
    title = "Whisper"
    description = "Writes down speech in 99 languages, a line at a time with times. Whisper large-v3-turbo (MIT) through MLX."
    runtime_model = WhisperRuntime
    inputs: ClassVar[dict[str, InputSpec]] = {"recording": RECORDING, "language": LANGUAGE, "terms": TERMS, "speakers": SPEAKERS, "split": SPLIT}
    transcribe = TranscribeInfo(
        guidance="The widest choice of languages. Words to expect steer the spelling; a quiet start can make it guess the wrong language, so name it then.",
        times="lines", speakers="turns", checked_minutes=56, roles=roles_of(inputs))
    # 2026-11-27, M5 Max: 17 minutes of speech in 8 s, 56 minutes in 31 s (3.8 GiB at the peak).
    timings: ClassVar[tuple[TimingSpec, ...]] = (TimingSpec(when={}, preset=None, gpu=0, seconds=8, note="for 17 minutes of speech"),)


class ParakeetRuntime(SpeechToTextRuntime):
    kind: Literal["parakeet_asr"]


class ParakeetPlugin(SpeechToTextPlugin):
    kind = "parakeet_asr"
    title = "Parakeet"
    description = ("The fastest of the four: 25 European languages, detected, a sentence at a time with times. NVIDIA Parakeet TDT 0.6B v3 "
                   "(CC-BY-4.0, credit NVIDIA) through MLX.")
    runtime_model = ParakeetRuntime
    inputs: ClassVar[dict[str, InputSpec]] = {"recording": RECORDING, "speakers": SPEAKERS, "split": SPLIT}
    transcribe = TranscribeInfo(
        guidance="Very fast. It detects the language itself and takes no word list, so rare names may be spelled by ear.", times="lines",
        speakers="turns", checked_minutes=56, roles=roles_of(inputs))
    # 2026-11-27, M5 Max: 17 minutes of speech in 4 s, 56 minutes in 12 s (3.9 GiB at the peak).
    timings: ClassVar[tuple[TimingSpec, ...]] = (TimingSpec(when={}, preset=None, gpu=0, seconds=4, note="for 17 minutes of speech"),)


class NemotronRuntime(SpeechToTextRuntime):
    kind: Literal["nemotron_asr"]


class NemotronPlugin(SpeechToTextPlugin):
    kind = "nemotron_asr"
    title = "Nemotron 3.5 Transcribe"
    description = ("The most accurate of the four, in 40 languages, with punctuation and numbers written out. "
                   "NVIDIA Nemotron 3.5 Transcribe 30B (OpenMDW-1.1), 4-bit early-access export through MLX. It has no times and does not label speakers.")
    runtime_model = NemotronRuntime
    inputs: ClassVar[dict[str, InputSpec]] = {"recording": RECORDING, "terms": TERMS}
    transcribe = TranscribeInfo(
        guidance=("Takes words to expect and writes numbers out in full. It has no times, so no captions, and no speaker labels: its own speaker tags "
                  "were unreliable in this 4-bit export."), times="none", speakers="none", checked_minutes=56, roles=roles_of(inputs))
    # 2026-11-27, M5 Max, in parts of two minutes: 56 minutes in 152 s, 17 minutes in about 45 s (19.8 GiB at the peak).
    timings: ClassVar[tuple[TimingSpec, ...]] = (TimingSpec(when={}, preset=None, gpu=0, seconds=45, note="for 17 minutes of speech"),)
