"""Meeting notes: a recording in; a transcript with speakers, a summary, action items and decisions out.

The worker (workers/meeting_notes_worker.py) runs the speech engine in WSL, one process per step, so the card is free
when the transcript is done. For the notes it asks the host for a text model (TextModelBroker in text_models.py), which
starts one through the normal capacity checks when none is running and stops it again afterwards if it started it.
"""
import importlib.util
import json
import os
import threading
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, TimingSpec
from .worker import WORKERS_DIR, WorkerPlugin, WorkerPreset, WorkerRuntime

TEXT_MODELS = {
    "auto": "A running text model, else the default",
    "flash_next": "Qwen3.8 Flash-Next",
    "deepseek41": "DeepSeek V4.1 Flash",
    "hy4_flash": "Tencent Hy4-Flash",
    "qwen38_27b": "Qwen3.8 27B",
    "inkling2": "Inkling 2 Mini",
}


class TranscriptEditError(ValueError):
    def __init__(self, message, code="TRANSCRIPT_INVALID", status=422):
        super().__init__(message)
        self.code, self.status = code, status


_EDIT_LOCK = threading.Lock()
_renderer = None


def _transcript_module():
    """workers/meeting_transcript.py, which writes the transcript files for the worker, so edits come out the same way."""
    global _renderer
    if _renderer is None:
        spec = importlib.util.spec_from_file_location("meeting_transcript", WORKERS_DIR / "meeting_transcript.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _renderer = module
    return _renderer


def _label(value, what):
    value = " ".join(str(value).split())
    if not value or len(value) > 80:
        raise TranscriptEditError(f"A {what} needs 1 to 80 characters.")
    return value


def _write(path: Path, text: str):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


class MeetingNotesPreset(WorkerPreset):
    pass


class MeetingNotesRuntime(WorkerRuntime):
    kind: Literal["meeting_notes"]
    presets: dict[str, MeetingNotesPreset] = Field(min_length=1)
    # The text model the notes use when none is running ("auto"), and those that cannot correct a transcript in a
    # useful time. Inkling always thinks, whatever reasoning_effort says, but at its lowest level (minimal) the
    # thinking is brief; the broker passes that level to the worker as `thinking_floor`.
    default_text_model: str = "flash_next"
    no_correction_models: list[str] = Field(default_factory=list)


class MeetingNotesPlugin(WorkerPlugin):
    kind = "meeting_notes"
    title = "Meeting notes"
    description = ("Turns a meeting recording (or a transcript you already have) into a transcript with who said what, then a summary, action items and "
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
        # 2026-11-24, M5 Max, a 19-minute recording: 90 s of speech, then 75 s correcting and 12 s for the notes.
        TimingSpec(when={}, preset="mac", seconds=140, note="for a 30-minute meeting, before the notes (about 3 minutes more)"),
    )
    modes: ClassVar[dict[str, ModeSpec]] = {
        "notes": ModeSpec(
            label="From a recording or transcript",
            help=("Add a recording of the meeting (a Zoom MP4 or M4A, or any audio or video) or a transcript you already have "
                  "(.vtt, .srt, .txt or .md). Everything stays on this computer."),
            inputs={
                "recording": InputSpec(
                    label="Recording or transcript", kind="files", accept=("audio", "video", "transcript"), max_count=1, required=True,
                    help=("The meeting's audio or video, up to about an hour, or a transcript file. A transcript skips "
                          "the speech step and goes straight to correction and notes.")),
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
                "video_names": InputSpec(
                    label="Read speaker names from the video", kind="choice", options=("yes", "no"), default="yes", advanced=True,
                    help="For a video of a Zoom or Meet call: reads the name shown under the active speaker and uses it as "
                         "the speaker's label. Without it, or where no name shows, speakers are numbered."),
                "correct": InputSpec(
                    label="Correct the transcript", kind="choice", options=("yes", "no"), default="yes", advanced=True,
                    help="Yes lets the text model fix misheard words and names before the notes."),
            }),
    }

    def check_inputs(self, mode, values, files):
        return []

    def edit_transcript(self, folder: Path, payload: dict):
        """Apply a person's corrections to a finished meeting: `rename` {old label: new label} everywhere, and per-segment
        `segments` [{index, speaker?, text?}]. Rewrites meeting.json and the transcript files from it (the notes and the
        uncorrected transcript-raw.json are left as they were) and returns the new revision."""
        path = folder / "meeting.json"
        with _EDIT_LOCK:
            if not path.is_file():
                raise TranscriptEditError("This result has no transcript to edit.", "JOB_NOT_FOUND", 404)
            record = json.loads(path.read_text(encoding="utf-8"))
            revision = int(record.get("revision", 1))
            if payload.get("revision") != revision:
                raise TranscriptEditError("The transcript changed since you opened it. Reload it and edit again.", "TRANSCRIPT_CHANGED", 409)
            segs = [dict(seg) for seg in record.get("segments") or []]
            names = dict(record.get("speakers") or {})
            for old, new in (payload.get("rename") or {}).items():
                new = _label(new, "speaker name")
                if not any(seg["speaker"] == old for seg in segs):
                    raise TranscriptEditError(f"There is no speaker {old!r}.")
                for seg in segs:
                    if seg["speaker"] == old:
                        seg["speaker"] = new
                names.pop(old, None)  # a name a person typed replaces the one the notes proposed
            for edit in payload.get("segments") or []:
                index = edit.get("index")
                if not isinstance(index, int) or not 0 <= index < len(segs):
                    raise TranscriptEditError(f"There is no segment {index!r}.")
                if edit.get("speaker") is not None:
                    segs[index]["speaker"] = _label(edit["speaker"], "speaker name")
                if edit.get("text") is not None:
                    text = " ".join(str(edit["text"]).split())
                    if not text:
                        raise TranscriptEditError("A segment cannot be empty.")
                    segs[index]["text"] = text
            names = {label: name for label, name in names.items() if any(seg["speaker"] == label for seg in segs)}
            record.update(segments=segs, speakers=names, revision=revision + 1, edited=True)
            files = _transcript_module().render(segs, names)
            for name, text in files.items():
                _write(folder / name, text)
            _write(path, json.dumps(record, indent=1))
            return {"revision": revision + 1, "segments": len(segs)}
