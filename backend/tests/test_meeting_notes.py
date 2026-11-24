"""Meeting notes: the plugin's form, and the worker's correction, notes and files (no model, no WSL)."""
import csv
import json
import sys
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, validate_inputs

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
import meeting_notes_worker as worker  # noqa: E402

PLUGIN = get_plugin("meeting_notes")
MODEL = {"base_url": "http://127.0.0.1:1", "model": "m"}


class Job:
    def __init__(self, folder):
        self.dir, self.outputs, self.details, self.progress, self.cancel_requested = Path(folder), [], {}, [], False

    def report(self, text):
        self.progress.append(text)

    def detail(self, **values):
        self.details.update(values)

    def output(self, name, mime):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.outputs.append({"name": name, "mime": mime})
        return self.dir / name


def segs(*texts):
    return [{"speaker": f"s{i % 2}", "start": 10.0 * i, "end": 10.0 * i + 8, "text": t} for i, t in enumerate(texts)]


def test_the_form_needs_a_recording_and_offers_transcript_or_notes():
    upload = {"u1": {"id": "u1", "kind": "audio", "mime": "audio/mp4", "name": "call.m4a", "bytes": 10}}
    values = validate_inputs(PLUGIN, {"mode": "notes", "recording": ["u1"]}, upload.get)
    assert values["notes"] == "notes" and values["text_model"] == "auto" and values["correct"] == "yes"
    with pytest.raises(SettingsError):
        validate_inputs(PLUGIN, {"mode": "notes"}, upload.get)
    assert PLUGIN.output_kind == "document" and PLUGIN.text_model_jobs


def test_speakers_are_numbered_in_order_of_first_appearance():
    labelled = worker.label_speakers([{"speaker": "7", "start": 0, "end": 1, "text": "a"},
                                      {"speaker": "2", "start": 1, "end": 2, "text": "b"},
                                      {"speaker": "7", "start": 2, "end": 3, "text": "c"}])
    assert [s["speaker"] for s in labelled] == ["Speaker 1", "Speaker 2", "Speaker 1"]


def test_correction_keeps_turns_that_change_too_much_and_chunks_that_fail(monkeypatch, tmp_path):
    answers = iter([json.dumps({"turns": [{"n": 0, "text": "Let's start the budget review."},
                                          {"n": 1, "text": "I think so. And also a lot of extra words that were never said here."}]})])
    monkeypatch.setattr(worker, "chat", lambda model, prompt, max_tokens, thinking=True: next(answers))
    fixed, stats = worker.correct(MODEL, segs("Let's start the budge it review.", "I think so."), "", Job(tmp_path))
    assert [s["text"] for s in fixed] == ["Let's start the budget review.", "I think so."]
    assert stats == {"turns_corrected": 1, "corrections_refused": 1, "chunks_not_corrected": 0}
    monkeypatch.setattr(worker, "chat", lambda *a, **k: "not json")
    fixed, stats = worker.correct(MODEL, segs("hello"), "", Job(tmp_path))
    assert fixed[0]["text"] == "hello" and stats["chunks_not_corrected"] == 1


def test_notes_are_checked_and_cleaned(monkeypatch):
    replies = iter(["{\"summary\": \"not a list\"}", json.dumps({
        "speakers": {"Speaker 1": "Anna", "Speaker 2": None},
        "summary": ["Budget agreed", ""], "actions": [{"task": "Send the plan", "owner": "Anna", "due": "Friday", "time": "00:10"}, {"owner": "x"}],
        "decisions": [{"decision": "Price is 25 euro", "by": None, "time": "00:20"}]})])
    monkeypatch.setattr(worker, "chat", lambda *a, **k: next(replies))
    notes = worker.extract(MODEL, worker.label_speakers(segs("a", "b")), "Anna")
    assert notes["summary"] == ["Budget agreed"] and len(notes["actions"]) == 1 and len(notes["decisions"]) == 1
    monkeypatch.setattr(worker, "chat", lambda *a, **k: "```json\n{}\n```")
    with pytest.raises(RuntimeError, match="could not be read"):
        worker.extract(MODEL, segs("a"), "")


def test_the_files_name_speakers_and_open_as_markdown_srt_and_csv(tmp_path):
    job = Job(tmp_path / "job")
    labelled = worker.label_speakers(segs("Hello, everyone.", "Morning, Anna.", "Let's decide the price."))
    notes = {"summary": ["Price set"], "actions": [{"task": "Send the plan", "owner": "Ben", "due": None, "time": "00:20"}],
             "decisions": [{"decision": "25 euro", "by": "Anna", "time": "00:20"}]}
    worker.write_outputs(job, labelled, notes, {"Speaker 1": "Anna"}, raw=[{"speaker": "0"}])
    names = [o["name"] for o in job.outputs]
    assert names == ["transcript.md", "transcript.srt", "transcript-raw.json", "notes.md", "actions.csv", "decisions.csv", "meeting.json"]
    md = (job.dir / "transcript.md").read_text(encoding="utf-8")
    assert "**[00:00] Speaker 1 (Anna):** Hello, everyone." in md and "**[00:10] Speaker 2:** Morning, Anna." in md
    srt = (job.dir / "transcript.srt").read_text(encoding="utf-8").splitlines()
    assert srt[:3] == ["1", "00:00:00,000 --> 00:00:08,000", "Speaker 1 (Anna): Hello, everyone."]
    rows = list(csv.reader((job.dir / "actions.csv").open(encoding="utf-8-sig")))
    assert rows == [["Task", "Owner", "Due", "Time"], ["Send the plan", "Ben", "", "00:20"]]
    notes_md = (job.dir / "notes.md").read_text(encoding="utf-8")
    assert "- [ ] Send the plan — Ben (00:20)" in notes_md and "- 25 euro — Anna (00:20)" in notes_md
    record = json.loads((job.dir / "meeting.json").read_text(encoding="utf-8"))
    assert record["speakers"] == {"Speaker 1": "Anna"} and record["decisions"][0]["decision"] == "25 euro"


def test_a_transcript_only_job_writes_no_notes_files(tmp_path):
    job = Job(tmp_path / "job")
    worker.write_outputs(job, worker.label_speakers(segs("Hi.")), None, {}, raw=None)
    assert [o["name"] for o in job.outputs] == ["transcript.md", "transcript.srt", "meeting.json"]


def test_times_read_as_minutes_and_seconds_and_hours_when_long():
    assert worker.mmss(65) == "01:05" and worker.mmss(3725) == "1:02:05"
    assert worker.srt_time(3725.5) == "01:02:05,500"
