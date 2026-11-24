"""Meeting notes: a recording in; a transcript with speakers, a summary, action items and decisions out.

The worker (workers/meeting_notes_worker.py) runs the speech engine in WSL, one process per step, so the card is free
when the transcript is done. For the notes it asks the host for a text model (TextModelBroker in text_models.py), which
starts one through the normal capacity checks when none is running and stops it again afterwards if it started it.
"""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

TEXT_MODELS = {
    "auto": "A running text model, else the default",
    "flash_next": "Qwen3.8 Flash-Next",
    "deepseek41": "DeepSeek V4.1 Flash",
    "inkling2": "Inkling 2 Mini",
}


class MeetingNotesPreset(WorkerPreset):
    pass


class MeetingNotesRuntime(WorkerRuntime):
    kind: Literal["meeting_notes"]
    presets: dict[str, MeetingNotesPreset] = Field(min_length=1)
    # The text model the notes use when none is running ("auto"), and those too small to correct a transcript
    # reliably (Inkling deliberates on every word and runs out of room).
    default_text_model: str = "flash_next"
    no_correction_models: list[str] = Field(default_factory=lambda: ["inkling2"])


class MeetingNotesPlugin(WorkerPlugin):
    kind = "meeting_notes"
    title = "Meeting notes"
    description = ("Turns a meeting recording into a transcript with who said what, then a summary, action items and "
                   "decisions you can download. It starts a text model for the notes if none is running.")
    runtime_model = MeetingNotesRuntime
    worker_script = "meeting_notes_worker.py"
    max_gpus = 1
    output_kind = "document"
    make_label = "Make notes"
    result_noun = "meeting"
    text_model_jobs = True  # its jobs ask the host for a text model (TextModelBroker)
    # 2026-11-23, AMI meetings of 14-36 minutes, speech step only (the notes add 1-3 minutes on Flash-Next).
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(when={}, preset="nemotron", seconds=300, note="for a 30-minute meeting, with the speech model's start"),
        TimingSpec(when={}, preset="qwen", seconds=90, note="for a 30-minute meeting"),
        TimingSpec(when={}, preset="vibevoice", seconds=240, note="for a 30-minute meeting"),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "notes": ModeSpec(
            label="From a recording",
            help="Add a recording of the meeting (a Zoom MP4 or M4A, or any audio). Everything stays on this computer.",
            inputs={
                "recording": InputSpec(
                    label="Recording", kind="files", accept=("audio", "video"), max_count=1, required=True,
                    help="The meeting's audio or video, up to about an hour."),
                "notes": InputSpec(
                    label="Make", kind="choice", options=("notes", "transcript"), default="notes",
                    option_labels={"notes": "Transcript and notes", "transcript": "Transcript only"},
                    help="Notes add a summary, action items and decisions, written by a text model."),
                "people": InputSpec(
                    label="Who was there", kind="text", max_length=500, placeholder="Anna, Ben, Chloe",
                    help="Optional: names help the notes say who said and agreed what."),
                "terms": InputSpec(
                    label="Names and terms", kind="textarea", max_length=500,
                    placeholder="Generation Station, Basalt, Q3 roadmap",
                    help="Optional: product names, jargon and spellings that come up, to get them right."),
                "text_model": InputSpec(
                    label="Text model for the notes", kind="choice", options=tuple(TEXT_MODELS), default="auto",
                    option_labels=TEXT_MODELS, advanced=True,
                    help="Which model writes the notes. It is started for this job if it is not running, and stopped "
                         "again afterwards; it must fit beside whatever else is running."),
                "correct": InputSpec(
                    label="Correct the transcript", kind="choice", options=("yes", "no"), default="yes", advanced=True,
                    help="Yes lets the text model fix misheard words and names before the notes (skipped on Inkling 2 "
                         "Mini, which is too small for it)."),
            }),
    }

    def check_inputs(self, mode, values, files):
        return []
