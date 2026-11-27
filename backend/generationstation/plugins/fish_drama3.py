"""Fish Audio Drama 3: expressive speech directed with [tags] in the text.

Two setups run inside WSL: Fast, the NVFP4 checkpoint on SGLang-Omni on the RTX 5090, and Full quality, the official
checkpoint on Fish Audio's own code over both cards. The Windows worker starts and
watches that server. See workers/fish_drama3_worker.py.
"""
import re
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .speech import Cues, Direction, SpeechInfo
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

LINE = re.compile(r"^\s*([^:\n]{1,40}):\s*\S")
GUIDE = (
    ("Direction: put a cue in square brackets where it should happen, in plain words: [whispers], [laughs], "
     "[sighs], [angry], [super happy], [nervous], [chuckles], [pause], [shouting], [crying], [sarcastic], "
     "[professional broadcast tone]. Any short description works; it applies from that point on."),
    "Pauses: punctuation shapes the reading. Commas give short pauses, full stops longer ones; [pause] adds one.",
    ("Numbers: write them the way they should be read, for example \"eighteen ninety-two\" rather than 1892, "
     "and \"ten dollars\" rather than $10."),
    "Languages: about 80, with English, Chinese and Japanese the strongest. Write the text in its own script.",
    "Length: long texts are split into parts and joined automatically.",
)
TEXT = InputSpec(
    label="What to say", kind="textarea", required=True, max_length=5000,
    placeholder="[whispers] Don't wake the baby. She just fell asleep. [laughs softly] Okay, okay, I'll be quiet.",
    help="The words to speak, with directions in square brackets such as [whispers] or [laughs]; see the writing "
         "guide below.", guide=GUIDE)
SCRIPT = InputSpec(
    label="Script", kind="textarea", required=True, max_length=5000,
    placeholder="Anna: [nervous] Did you hear that? Something's downstairs.\nBen: [sleepy] It's just the wind. "
                "Go back to sleep.\nAnna: [whispering] The wind doesn't open doors.",
    help="One line per turn, starting with the speaker's name and a colon. Directions in square brackets work "
         "as in the other tab.", guide=GUIDE)


SEED = InputSpec(
    label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
    help="Full quality only: reuse a seed to get the same performance again. Leave empty for a fresh take.")


class FishDrama3Preset(WorkerPreset):
    pass


class FishDrama3Runtime(WorkerRuntime):
    kind: Literal["fish_drama3"]
    presets: dict[str, FishDrama3Preset] = Field(min_length=1)


class FishDrama3Plugin(WorkerPlugin):
    kind = "fish_drama3"
    title = "Fish Audio Drama 3"
    description = ("Expressive speech you direct with cues in the text, such as [whispers] or [laughs], in a "
                   "voice cloned from a short sample or chosen by the model; also scenes with several voices. "
                   "Fast runs on the RTX 5090; Full quality is more expressive, a little slower, and needs both cards.")
    runtime_model = FishDrama3Runtime
    worker_script = "fish_drama3_worker.py"
    max_gpus = 2
    output_kind = "audio"
    gpu_helpers = ("vmwp",)  # its server runs in WSL; Windows reports that memory under the VM's process
    make_label = "Make speech"
    result_noun = "recording"
    # RTX 5090 (4-bit checkpoint, SGLang-Omni in WSL), 2026-11-23: 6-8 s of speech in 0.8-0.9 s, 19 s in 2.4 s;
    # the first request after a start took 4.8 s. Multi-speaker scenes of 8-15 s took 1-2 s per take.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        # NVFP4 on the RTX 5090 (SGLang-Omni in WSL), 2026-11-23: 7-15 s scenes in 2.2-4.8 s.
        TimingSpec(when={"mode": "speak"}, preset="nvfp4", seconds=3, note="for about 10 s of speech"),
        TimingSpec(when={"mode": "scene"}, preset="nvfp4", seconds=4, note="for a short scene"),
        # Full model over both cards (Fish Audio's code with per-card CUDA graphs), 2026-11-23: 12-13 s takes in
        # 6-6.5 s (17-21 s before the graphs).
        TimingSpec(when={"mode": "speak"}, preset="full", seconds=5, note="for about 10 s of speech"),
        TimingSpec(when={"mode": "scene"}, preset="full", seconds=7, note="for a short scene"),
    )
    speech: ClassVar[SpeechInfo] = SpeechInfo(
        voices={"own": "speak", "clone": "speak"}, scene="scene",
        direction=Direction(
            text=("Direct it with cues in square brackets in the text. Any short description works, and it applies from "
                  "that point on."),
            cues=Cues(open="[", close="]", kind="emotion", open_vocabulary=True,
                      examples=["[whispers]", "[laughs]", "[sighs]", "[angry]", "[super happy]", "[nervous]", "[pause]",
                                "[shouting]", "[crying]", "[sarcastic]"],
                      text="Put a cue in square brackets where it should happen, in plain words.")),
        roles={
            "speak": {"text": "prompt", "seed": "seed", "sample": "sample", "sample_text": "sample_text"},
            "scene": {"text": "script", "seed": "seed", "sample": "voices", "sample_text": "voice_texts"},
        })
    modes: ClassVar[dict[str, ModeSpec]] = {
        "speak": ModeSpec(
            label="Speak a text",
            help="Write what to say with directions in brackets. Add a voice sample to speak in that voice, or "
                 "leave it out for a voice the model chooses. Only clone voices you have permission to use.",
            inputs={
                "sample": InputSpec(
                    label="Voice sample", kind="files", accept=("audio",), max_count=1,
                    help="Optional: 5-15 seconds of one person speaking clearly, without music. Without one, the "
                         "model picks a voice, a different one each time."),
                "sample_text": InputSpec(
                    label="What the sample says", kind="text", max_length=1000,
                    help="The exact words in the sample. Typing them gives a closer copy of the voice."),
                "prompt": TEXT, "seed": SEED,
            }),
        "scene": ModeSpec(
            label="A scene with several voices",
            help="Write a dialogue, one line per turn. Drama 3 performs the characters together, in up to three "
                 "voices per passage, so they react to each other. Characters without a sample get a voice from "
                 "the model and keep it for the whole scene.",
            inputs={
                "script": SCRIPT,
                "voices": InputSpec(
                    label="Voice samples", kind="files", accept=("audio",), max_count=4,
                    help="Optional: one sample per character, in the order the characters first speak. Characters "
                         "without one get a voice from the model."),
                "voice_texts": InputSpec(
                    label="What the samples say", kind="textarea", max_length=2000,
                    help="Optional: the words of each sample, one line per sample in the same order."),
                "seed": SEED,
            }),
    }

    def gpu_limit(self, preset):
        return len(preset.gpus)

    def check_gpus(self, preset, gpus):
        """Each setup runs on its own cards: Fast on the RTX 5090, Full quality over both."""
        if sorted(gpus) != sorted(preset.gpus):
            names = " and ".join(f"GPU {g}" for g in preset.gpus)
            return [f"{preset.name} runs on {names}."]
        return []

    def check_inputs(self, mode, values, files):
        if mode != "scene":
            return []
        lines = [line for line in (values.get("script") or "").splitlines() if line.strip()]
        if lines and not LINE.match(lines[0]):
            return ['Start each line of the script with a name and a colon, such as "Anna: Hello."']
        names = {LINE.match(line).group(1).strip() for line in lines if LINE.match(line)}
        if len(names) > 8:
            return ["Use at most 8 characters in one scene."]
        return []
