"""ACE-Step 1.5: songs with vocals, or instrumentals, from a style description and lyrics."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .music import MusicInfo
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

LANGUAGES = ("en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru")


class AceStepPreset(WorkerPreset):
    pass


class AceStepRuntime(WorkerRuntime):
    kind: Literal["ace_step"]
    presets: dict[str, AceStepPreset] = Field(min_length=1)


KEYS = ("auto",) + tuple(f"{note} {scale}" for note in ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B") for scale in ("major", "minor"))

STYLE = InputSpec(
    label="Style", kind="text", required=True, max_length=400,
    placeholder="Warm acoustic pop, female vocal, fingerpicked guitar, 96 BPM",
    help="The genre, mood, instruments, voice and tempo, separated by commas.")
LYRICS = InputSpec(
    label="Lyrics", kind="textarea", max_length=4000,
    placeholder="[Verse]\nMorning light across the quiet street\n\n[Chorus]\nSing it out loud, we're moving on",
    help="Put each part under a tag: [Verse], [Chorus], [Bridge], [Outro]. Leave this empty for an instrumental.")
LANGUAGE = InputSpec(label="Language", kind="choice", options=LANGUAGES, default="en", help="The language the lyrics are sung in.", advanced=True)
TEMPO = InputSpec(label="Tempo (BPM)", kind="int", minimum=30, maximum=300, placeholder="auto",
                  help="Beats per minute. Leave empty and the model picks one to suit the style.")
KEY = InputSpec(label="Key", kind="choice", options=KEYS, default="auto", help="The musical key. Auto lets the model choose.", advanced=True)
SIGNATURE = InputSpec(label="Time signature", kind="choice", options=("auto", "2/4", "3/4", "4/4", "6/8"), default="auto",
                      help="Beats per bar. Auto lets the model choose.", advanced=True)
SEED = InputSpec(label="Seed", kind="seed", minimum=0, maximum=2**31 - 1, advanced=True,
                 help="Reuse a seed to get the same song again. Leave empty for a new one.")
SOURCE = InputSpec(label="Song", kind="files", accept=("audio",), max_count=1, required=True,
                   help="The song to start from: one you made here (use its Use as source button) or a file from your computer. Its length is kept.")


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
    modes: ClassVar[dict[str, ModeSpec]] = {
        "song": ModeSpec(label="New song", help="Make a song from a style and lyrics.", inputs={
            "style": STYLE, "lyrics": LYRICS, "length": InputSpec(label="Length", kind="choice", options=("60", "30", "120"), default="60",
                                                                  help="Seconds of music. Longer songs need more memory."),
            "tempo": TEMPO, "language": LANGUAGE, "key": KEY, "time_signature": SIGNATURE, "seed": SEED}),
        "cover": ModeSpec(label="New version of a song", help="Make a new version of a song in another style, or with new lyrics.", inputs={
            "source": SOURCE, "style": STYLE.model_copy(update={"help": "The style of the new version, in the same words as for a new song."}), "lyrics": LYRICS.model_copy(update={"help": "The lyrics to sing. Leave empty for an instrumental."}),
            "strength": InputSpec(label="How closely it follows the song", kind="int", minimum=5, maximum=100, placeholder="50",
                                  help="Percent (50 if empty). Low: only the broad shape of the song stays. High: it stays close to the original."),
            "tempo": TEMPO, "language": LANGUAGE, "key": KEY, "time_signature": SIGNATURE, "seed": SEED}),
        "repaint": ModeSpec(label="Redo a section", help="Replace one part of a song and keep the rest.", inputs={
            "source": SOURCE, "start": InputSpec(label="From (seconds)", kind="int", minimum=0, maximum=600, default=0, help="Where the part to redo begins."),
            "end": InputSpec(label="To (seconds)", kind="int", minimum=1, maximum=600, placeholder="the end",
                             help="Where it ends. Leave empty to redo everything from the start point to the end."),
            "style": STYLE.model_copy(update={"help": "What the new part should sound like."}),
            "lyrics": LYRICS.model_copy(update={"help": "The lyrics for the new part. Leave empty for no singing."}),
            "language": LANGUAGE, "seed": SEED}),
    }

    music: ClassVar[MusicInfo] = MusicInfo(
        guidance=("Describe the genre, mood, instruments, voice and tempo in the style box, and write the lyrics under [Verse] and "
                  "[Chorus] tags (empty for an instrumental). It can also make a new version of a song in another style, or redo "
                  "one section of a song, which also extends it when the end of the section is past the end of the song."),
        create="song", cover="cover", repaint="repaint",
        roles={"song": {"style": "style", "lyrics": "lyrics", "length": "length", "language": "language", "tempo": "tempo", "key": "key",
                        "time_signature": "time_signature", "seed": "seed"},
               "cover": {"style": "style", "lyrics": "lyrics", "language": "language", "tempo": "tempo", "key": "key",
                         "time_signature": "time_signature", "seed": "seed", "source": "source", "strength": "strength"},
               "repaint": {"style": "style", "lyrics": "lyrics", "language": "language", "seed": "seed", "source": "source",
                           "start": "start", "end": "end"}})
