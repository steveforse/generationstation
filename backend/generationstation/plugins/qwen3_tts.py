"""Qwen3-TTS: speech in 10 languages from built-in voices you direct, voices you describe, or a cloned voice."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

# The 9 voices of Qwen3-TTS-12Hz-1.7B-CustomVoice (its README), with their native language.
SPEAKERS = {
    "Ryan": "Ryan: dynamic male voice with strong rhythm (English)",
    "Aiden": "Aiden: sunny American male voice, clear midrange (English)",
    "Vivian": "Vivian: bright, slightly edgy young female voice (Chinese)",
    "Serena": "Serena: warm, gentle young female voice (Chinese)",
    "Uncle_Fu": "Uncle Fu: seasoned male voice, low and mellow (Chinese)",
    "Dylan": "Dylan: youthful Beijing male voice, clear and natural (Chinese, Beijing dialect)",
    "Eric": "Eric: lively Chengdu male voice, slightly husky (Chinese, Sichuan dialect)",
    "Ono_Anna": "Ono Anna: playful Japanese female voice, light and nimble (Japanese)",
    "Sohee": "Sohee: warm Korean female voice with rich emotion (Korean)",
}
LANGUAGES = ("auto", "english", "chinese", "japanese", "korean", "german", "french", "russian", "portuguese",
             "spanish", "italian")

TEXT = InputSpec(
    label="What to say", kind="textarea", required=True, max_length=3000,
    placeholder="Good evening, and welcome aboard. Our next stop is Harbour Lights.",
    help="The words to speak. The model follows the meaning of the text for its tone, so write it the way it "
         "should sound; see the writing guide below.",
    guide=(
        ("Tone from the words: Qwen3-TTS reads the meaning and punctuation, so exclamation marks, questions and "
         "emotional wording come through. For a particular delivery, say so under 'How to say it'."),
        ("Pauses: commas give short pauses, full stops longer ones, and a new paragraph a clear break. An "
         "ellipsis (...) gives a hesitant pause."),
        ("Numbers and symbols: it reads most numbers, dates and symbols itself; write them out if a particular "
         "reading matters (\"nineteen ninety-two\", not 1992)."),
        ("Languages: Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish and "
         "Italian. Choose the language, or leave Auto. Every voice can speak every language, though each built-in "
         "voice sounds best in its own."),
        "Length: up to 3,000 characters per recording.",
    ))
STYLE = InputSpec(
    label="How to say it", kind="text", max_length=300,
    placeholder="Very happy, a little out of breath",
    help="Optional: the delivery, in plain words: emotion, speed, volume, attitude. For example 'Angry and fast', "
         "'Whisper, slowly', 'Sad, with long pauses', 'Excited, like a sports commentator'.")
LANGUAGE = InputSpec(
    label="Language", kind="choice", options=LANGUAGES, default="auto",
    help="The language of the text. Auto works it out; naming it is slightly better.")
SEED = InputSpec(
    label="Seed", kind="seed", minimum=0, maximum=2**31 - 1,
    help="Leave empty for a fresh take each time. Reuse a seed to get the same reading again.", advanced=True)


class Qwen3TTSPreset(WorkerPreset):
    pass


class Qwen3TTSRuntime(WorkerRuntime):
    kind: Literal["qwen3_tts"]
    presets: dict[str, Qwen3TTSPreset] = Field(min_length=1)


class Qwen3TTSPlugin(WorkerPlugin):
    kind = "qwen3_tts"
    title = "Qwen3-TTS"
    description = ("Speaks text in 10 languages with built-in voices you can direct ('say it angrily'), voices you "
                   "describe in your own words, or a voice cloned from a short sample.")
    runtime_model = Qwen3TTSRuntime
    worker_script = "qwen3_tts_worker.py"
    max_gpus = 1
    output_kind = "audio"
    make_label = "Make speech"
    result_noun = "recording"
    # RTX 4080 through the app, 2026-11-22 (H3 rendering on the other card): 11.6 s of speech in 15-17 s (built-in),
    # 13.7 s in 17-18 s (described), 8.3 s in 11 s (cloned). Switching tabs moves models: the first job after a
    # switch, or the first use of a tab, takes a few seconds more.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(when={"mode": "builtin"}, gpu=1, seconds=19, first_seconds=22, note="for about 15 s of speech"),
        TimingSpec(when={"mode": "design"}, gpu=1, seconds=19, first_seconds=28, note="for about 15 s of speech"),
        TimingSpec(when={"mode": "clone"}, gpu=1, seconds=20, first_seconds=28, note="for about 15 s of speech"),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "builtin": ModeSpec(
            label="Built-in voices",
            help="Choose one of 9 voices and, if you like, say how it should be spoken.",
            inputs={
                "speaker": InputSpec(label="Voice", kind="choice", options=tuple(SPEAKERS), default="Ryan",
                                     option_labels=SPEAKERS,
                                     help="Each voice can speak every language, but sounds best in its own."),
                "prompt": TEXT, "style": STYLE, "language": LANGUAGE, "seed": SEED,
            }),
        "design": ModeSpec(
            label="Describe a voice",
            help="Describe the voice in your own words: who is speaking and how they sound.",
            inputs={
                "voice": InputSpec(
                    label="Voice", kind="textarea", required=True, max_length=600,
                    placeholder="A woman in her sixties with a soft Welsh lilt, warm and unhurried, slightly husky",
                    help="Free description: age, gender, accent, voice quality (husky, bright, nasal), character "
                         "and mood. More detail gives a more specific voice.",
                    guide=(
                        "Who: age, gender and where they're from: 'a man in his forties from Glasgow'.",
                        "Sound: pitch and texture: 'deep and gravelly', 'bright and clear', 'breathy', 'nasal'.",
                        ("Character: 'a tired night-shift nurse', 'an overexcited game-show host', 'a stern "
                         "headmistress'."),
                        ("Examples from Qwen: 'Male, 17 years old, tenor range, gaining confidence - deeper breath "
                         "support now, though vowels still tighten when nervous.' 'Speak in an incredulous tone, "
                         "but with a hint of panic beginning to creep into your voice.'"),
                    )),
                "prompt": TEXT, "style": STYLE, "language": LANGUAGE, "seed": SEED,
            }),
        "clone": ModeSpec(
            label="From a voice sample",
            help=("Give about 3-20 seconds of someone speaking clearly; Qwen3-TTS speaks your text in that voice. "
                  "Only clone voices you have permission to use."),
            inputs={
                "sample": InputSpec(
                    label="Voice sample", kind="files", accept=("audio",), max_count=1,
                    help="3-20 seconds of one person speaking, without music or noise."),
                "sample_text": InputSpec(
                    label="What the sample says", kind="text", max_length=1000,
                    placeholder="Recommended: the exact words in the sample",
                    help=("The exact words spoken in the sample. Left empty, only the voice's character is copied, "
                          "which Qwen says can lower the likeness.")),
                "prompt": TEXT, "language": LANGUAGE, "seed": SEED,
            }),
    }

    def check_inputs(self, mode, values, files):
        if mode == "clone" and not files.get("sample"):
            return ["Add a voice sample."]
        return []
