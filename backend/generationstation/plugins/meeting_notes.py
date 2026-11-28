"""Meeting notes: a recording in; a transcript with speakers, a summary, action items and decisions out.

The worker (workers/meeting_notes_worker.py) runs the speech engine in WSL, one process per step, so the card is free
when the transcript is done. For the notes it asks the host for a text model (TextModelBroker in text_models.py), which
starts one through the normal capacity checks when none is running and stops it again afterwards if it started it.
"""
import difflib
import importlib.util
import json
import os
import threading
from datetime import UTC, datetime
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


def _write(path: Path, text: str, *, exact: bool = False):
    """Replace a file in one step. `exact` keeps line endings as given (CSV files end lines with \\r\\n)."""
    temp = path.with_name(path.name + ".tmp")
    if exact:
        with open(temp, "w", newline="", encoding="utf-8") as handle:
            handle.write(text)
    else:
        temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


MAX_HISTORY = 200  # entries kept in meeting.json, newest last
MAX_CHANGES = 200  # changes kept in one entry


def _diff(section: str, before: list[str], after: list[str]) -> list[dict]:
    """What changed between two lists of lines: removed, added, and changed (a line replaced by another)."""
    changes = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old, new = before[i1:i2], after[j1:j2]
        for old_line, new_line in zip(old, new):
            changes.append({"section": section, "kind": "changed", "before": old_line, "after": new_line})
        changes += [{"section": section, "kind": "removed", "before": line, "after": None} for line in old[len(new):]]
        changes += [{"section": section, "kind": "added", "before": None, "after": line} for line in new[len(old):]]
    return changes


def _log(record: dict, revision: int, changes: list[dict]):
    """Append a history entry for a saved edit: when, the new revision, and what changed."""
    entry = {"revision": revision, "at": datetime.now(UTC).isoformat(timespec="seconds"), "changes": changes[:MAX_CHANGES]}
    if len(changes) > MAX_CHANGES:
        entry["more"] = len(changes) - MAX_CHANGES
    record["history"] = [*(record.get("history") or []), entry][-MAX_HISTORY:]


def _line(value, what, limit):
    value = " ".join(str(value).split())
    if not value or len(value) > limit:
        raise TranscriptEditError(f"A {what} needs 1 to {limit} characters.")
    return value


def _item(value, main, extras, what):
    """A person's action item or decision: its main text is required, the other fields (owner, due, time) are optional."""
    if not isinstance(value, dict):
        raise TranscriptEditError(f"A {what} must be an object.")
    item = {main: _line(value.get(main) or "", f"{what} {main}", 400)}
    for key in extras:
        text = " ".join(str(value.get(key) or "").split())
        if len(text) > 80:
            raise TranscriptEditError(f"The {key} of a {what} can be at most 80 characters.")
        if text:
            item[key] = text
    return item


def _write_notes(folder: Path, record: dict):
    notes = {section: record.get(section) or [] for section in ("summary", "actions", "decisions")}
    files = _transcript_module().render_notes(notes, record.get("speakers") or {})
    for name, text in files.items():
        _write(folder / name, text, exact=name.endswith(".csv"))


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
            changes = []
            for old, new in (payload.get("rename") or {}).items():
                new = _label(new, "speaker name")
                if not any(seg["speaker"] == old for seg in segs):
                    raise TranscriptEditError(f"There is no speaker {old!r}.")
                count = 0
                for seg in segs:
                    if seg["speaker"] == old:
                        seg["speaker"] = new
                        count += 1
                changes.append({"section": "transcript", "kind": "renamed", "before": old, "after": new, "detail": f"{count} segment{'s' if count != 1 else ''}"})
                names.pop(old, None)  # a name a person typed replaces the one the notes proposed
            for edit in payload.get("segments") or []:
                index = edit.get("index")
                if not isinstance(index, int) or not 0 <= index < len(segs):
                    raise TranscriptEditError(f"There is no segment {index!r}.")
                was = f"{segs[index]['speaker']}: {segs[index]['text']}"
                if edit.get("speaker") is not None:
                    segs[index]["speaker"] = _label(edit["speaker"], "speaker name")
                if edit.get("text") is not None:
                    text = " ".join(str(edit["text"]).split())
                    if not text:
                        raise TranscriptEditError("A segment cannot be empty.")
                    segs[index]["text"] = text
                now = f"{segs[index]['speaker']}: {segs[index]['text']}"
                if now != was:
                    changes.append({"section": "transcript", "kind": "changed", "before": was, "after": now, "detail": f"segment {index + 1}"})
            names = {label: name for label, name in names.items() if any(seg["speaker"] == label for seg in segs)}
            record.update(segments=segs, speakers=names, revision=revision + 1, edited=True)
            if changes:
                _log(record, revision + 1, changes)
            files = _transcript_module().render(segs, names)
            for name, text in files.items():
                _write(folder / name, text)
            _write(path, json.dumps(record, indent=1))
            return {"revision": revision + 1, "segments": len(segs)}

    def edit_notes(self, folder: Path, payload: dict):
        """Replace a finished meeting's summary, action items and/or decisions with a person's version. Each list sent
        replaces the one saved. Rewrites meeting.json, notes.md and the two CSV files, logs what changed in the history
        and returns the new revision. The notes as first written are kept once, as `notes_original`."""
        path = folder / "meeting.json"
        with _EDIT_LOCK:
            if not path.is_file():
                raise TranscriptEditError("This result has no notes to edit.", "JOB_NOT_FOUND", 404)
            record = json.loads(path.read_text(encoding="utf-8"))
            if "summary" not in record:
                raise TranscriptEditError("This meeting was made without notes.", "JOB_NOT_FOUND", 404)
            revision = int(record.get("revision", 1))
            if payload.get("revision") != revision:
                raise TranscriptEditError("The notes changed since you opened them. Reload them and edit again.", "TRANSCRIPT_CHANGED", 409)
            module = _transcript_module()
            lines = {"summary": lambda item: item, "actions": module.action_line, "decisions": module.decision_line}
            before = {section: record.get(section) or [] for section in lines}
            after = dict(before)
            if payload.get("summary") is not None:
                after["summary"] = [_line(item, "summary point", 600) for item in payload["summary"]]
            if payload.get("actions") is not None:
                after["actions"] = [_item(item, "task", ("owner", "due", "time"), "action item") for item in payload["actions"]]
            if payload.get("decisions") is not None:
                after["decisions"] = [_item(item, "decision", ("by", "time"), "decision") for item in payload["decisions"]]
            changes = []
            for section, show in lines.items():
                changes += _diff(section, [show(item) for item in before[section]], [show(item) for item in after[section]])
            if not changes and all(after[key] == before[key] for key in after):
                raise TranscriptEditError("Nothing was changed.")
            record.setdefault("notes_original", before)
            record.update(after, revision=revision + 1, edited=True)
            _log(record, revision + 1, changes)
            _write_notes(folder, record)
            _write(path, json.dumps(record, indent=1))
            return {"revision": revision + 1, "changes": len(changes)}
