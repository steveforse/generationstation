"""OmniVoice: speech from text in 600+ languages, in a cloned or described voice."""
import re
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .speech import Cues, Direction, SpeechInfo
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

# The sounds OmniVoice knows (omnivoice/models/omnivoice.py, _NONVERBAL_PATTERN), with what each one is.
SOUNDS = {
    "laughter": "a laugh", "sigh": "a sigh",
    "surprise-ah": "a surprised 'ah!'", "surprise-oh": "a surprised 'oh!'", "surprise-wa": "a surprised 'wah!'",
    "surprise-yo": "a surprised 'yo!'",
    "question-ah": "a questioning 'ah?'", "question-oh": "a questioning 'oh?'", "question-ei": "a questioning 'eh?'",
    "question-yi": "a questioning 'yi?'", "question-en": "a questioning 'hm?'",
    "confirmation-en": "an agreeing 'mm-hm'", "dissatisfaction-hnn": "an annoyed 'hmph'",
}
# A pronunciation in CMU phonemes: capital letters, a stress digit on vowels, separated by spaces ([B EY1 S]).
PHONEMES = re.compile(r"^[A-Z]{1,3}[0-2]?( [A-Z]{1,3}[0-2]?)*$")
BRACKETS = re.compile(r"\[([^\[\]]*)\]")

TEXT = InputSpec(
    label="What to say", kind="textarea", required=True, max_length=5000,
    placeholder="Good evening, and welcome aboard. Our next stop is Harbour Lights. [laughter] Mind the gap!",
    help="The words to speak, in any of 600+ languages. Square brackets add a sound such as [laughter] or fix a "
         "pronunciation; see the writing guide below.",
    guide=(
        ("Pauses: punctuation shapes the reading. Commas give short pauses, full stops longer ones; a new "
         "paragraph is a clear break. Question and exclamation marks change the tone."),
        ("Sounds: put one of these in square brackets where it should happen: "
         + "; ".join(f"[{tag}] {meaning}" for tag, meaning in SOUNDS.items())
         + ". Other words in brackets are not allowed."),
        ("Pronunciation: to fix a word, replace it with its sounds in brackets, written in CMU phonemes (capital "
         "letters, with 0, 1 or 2 after vowels for stress): [B EY1 S] for bass the instrument, [B AE1 S] for the "
         "fish. For Chinese, write pinyin in capitals with the tone number, such as ZHONG1."),
        ("Numbers: write numbers, dates and amounts the way they should be read, for example \"eighteen "
         "ninety-two\" rather than 1892, and \"ten dollars\" rather than $10."),
        ("Other languages: write the text in that language and script, and set Language for the best result. "
         "A cloned voice can speak a different language from its sample."),
        "Length: up to 5,000 characters. Long texts are spoken in parts of about 15 seconds and joined.",
    ))
ANY = "any"
TRAITS = {
    "gender": InputSpec(label="Gender", kind="choice", options=(ANY, "female", "male"), default=ANY,
                        help="Any lets the model choose."),
    "age": InputSpec(label="Age", kind="choice",
                     options=(ANY, "child", "teenager", "young adult", "middle-aged", "elderly"), default=ANY,
                     help="Any lets the model choose."),
    "pitch": InputSpec(label="Pitch", kind="choice",
                       options=(ANY, "very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"),
                       default=ANY, help="How low or high the voice is. Any lets the model choose."),
    "accent": InputSpec(label="Accent", kind="choice",
                        options=(ANY, "american accent", "australian accent", "british accent", "canadian accent",
                                 "chinese accent", "indian accent", "japanese accent", "korean accent",
                                 "portuguese accent", "russian accent"), default=ANY,
                        help="The accent for English speech. Any lets the model choose."),
    "whisper": InputSpec(label="Whisper", kind="choice", options=("no", "yes"), default="no",
                         help="Yes makes the voice whisper."),
}
COMMON = {
    "language": InputSpec(
        label="Language", kind="text", max_length=40, placeholder="English",
        help="Optional: the language of the text, such as English, French or ja. Naming it helps a little; "
             "left empty, it is worked out from the text."),
    "speed": InputSpec(
        label="Speed", kind="choice", options=("slower", "normal", "faster"), default="normal",
        help="How fast the voice speaks."),
    "quality": InputSpec(
        label="Quality (steps)", kind="choice", options=("high", "standard"), default="standard",
        help="Standard: 32 steps, about a second for a paragraph. High: 64 steps, about twice as long, sometimes "
             "a little cleaner.", advanced=True),
    "seed": InputSpec(
        label="Seed", kind="seed", minimum=0, maximum=2**31 - 1,
        help="Leave empty for a fresh take each time. Reuse a seed to get the same reading again.", advanced=True),
}


def bracket_problems(text):
    """Bracketed spans OmniVoice would reject or misread: anything but a known sound or CMU phonemes."""
    bad = [span for span in BRACKETS.findall(text) if span not in SOUNDS and not PHONEMES.match(span)]
    return [f"[{span}]" for span in dict.fromkeys(bad)]


def instruct(values):
    """The voice description OmniVoice understands, from the chosen traits ("female, young adult, british accent")."""
    items = [values.get(key) for key in ("gender", "age", "pitch", "accent")]
    items = [item for item in items if item and item != ANY]
    if values.get("whisper") == "yes":
        items.append("whisper")
    return ", ".join(items)


class OmniVoicePreset(WorkerPreset):
    pass


class OmniVoiceRuntime(WorkerRuntime):
    kind: Literal["omnivoice"]
    presets: dict[str, OmniVoicePreset] = Field(min_length=1)


class OmniVoicePlugin(WorkerPlugin):
    kind = "omnivoice"
    title = "OmniVoice"
    description = "Speaks any text in 600+ languages, in a voice cloned from a short sample or described in words."
    runtime_model = OmniVoiceRuntime
    worker_script = "omnivoice_worker.py"
    max_gpus = 1
    output_kind = "audio"
    make_label = "Make speech"
    result_noun = "recording"
    # RTX 4080, 2026-11-21: 13 s of speech in 1.5 s (cloned voice), 7.5 s in 0.7 s (described voice).
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(when={"quality": "standard"}, gpu=1, seconds=1.5, note="for about 15 s of speech"),
        TimingSpec(when={"quality": "high"}, gpu=1, seconds=3, note="for about 15 s of speech"),
    )
    speech: ClassVar[SpeechInfo] = SpeechInfo(
        voices={"design": "design", "clone": "clone"},
        direction=Direction(
            text=("OmniVoice does not act emotions: it follows the words and punctuation, and has a speed setting and a "
                  "whisper switch. It can put a sound in the text (a laugh, a sigh), but only from its own list; any other "
                  "word in brackets is refused."),
            cues=Cues(open="[", close="]", kind="sounds", open_vocabulary=False,
                      examples=[f"[{tag}]" for tag in SOUNDS],
                      text="Put a sound in square brackets where it should happen. Only these sounds work.")),
        roles={
            "clone": {"text": "prompt", "language": "language", "seed": "seed", "speed": "speed", "sample": "sample", "sample_text": "sample_text"},
            "design": {"text": "prompt", "language": "language", "seed": "seed", "speed": "speed"},
        })
    modes: ClassVar[dict[str, ModeSpec]] = {
        "clone": ModeSpec(
            label="From a voice sample",
            help="Give 3-25 seconds of someone speaking clearly; OmniVoice speaks your text in that voice. Only "
                 "clone voices you have permission to use.",
            inputs={
                "sample": InputSpec(
                    label="Voice sample", kind="files", accept=("audio",), max_count=1,
                    help="3-25 seconds of one person speaking, without music or noise. Any language works, even "
                         "a different one from the text."),
                "sample_text": InputSpec(
                    label="What the sample says", kind="text", max_length=1000,
                    placeholder="Leave empty to have it written down automatically",
                    help="Optional: the exact words in the sample. Typing them is a little more accurate; left "
                         "empty, they are transcribed automatically (Whisper), which takes a few seconds more."),
                "prompt": TEXT, **COMMON,
            }),
        "design": ModeSpec(
            label="Describe a voice",
            help="Choose the voice's traits; anything left at Any is up to the model.",
            inputs={**TRAITS, "prompt": TEXT, **COMMON}),
    }

    def check_inputs(self, mode, values, files):
        problems = []
        if mode == "clone" and not files.get("sample"):
            problems.append("Add a voice sample.")
        bad = bracket_problems(values.get("prompt", ""))
        if bad:
            problems.append(f"What to say: {', '.join(bad)} is not a sound or pronunciation OmniVoice knows. Use one "
                            f"of the sounds in the writing guide, or CMU phonemes such as [B EY1 S].")
        return problems
