"""Meeting notes: the plugin's form, and the worker's correction, notes and files (no model, no WSL)."""
import csv
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, validate_inputs

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
import meeting_notes_worker as worker
import meeting_transcript

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
    assert names == ["transcript.md", "transcript.srt", "transcript.vtt", "transcript-raw.json", "notes.md", "actions.csv", "decisions.csv", "meeting.json"]
    md = (job.dir / "transcript.md").read_text(encoding="utf-8")
    assert "**[00:00] Speaker 1 (Anna):** Hello, everyone." in md and "**[00:10] Speaker 2:** Morning, Anna." in md
    srt = (job.dir / "transcript.srt").read_text(encoding="utf-8").splitlines()
    assert srt[:3] == ["1", "00:00:00,000 --> 00:00:08,000", "Speaker 1 (Anna): Hello, everyone."]
    vtt = (job.dir / "transcript.vtt").read_text(encoding="utf-8").splitlines()
    assert vtt[:5] == ["WEBVTT", "", "1", "00:00:00.000 --> 00:00:08.000", "Speaker 1 (Anna): Hello, everyone."]
    rows = list(csv.reader((job.dir / "actions.csv").open(encoding="utf-8-sig")))
    assert rows == [["Task", "Owner", "Due", "Time"], ["Send the plan", "Ben", "", "00:20"]]
    notes_md = (job.dir / "notes.md").read_text(encoding="utf-8")
    assert "- [ ] Send the plan — Ben (00:20)" in notes_md and "- 25 euro — Anna (00:20)" in notes_md
    record = json.loads((job.dir / "meeting.json").read_text(encoding="utf-8"))
    assert record["speakers"] == {"Speaker 1": "Anna"} and record["decisions"][0]["decision"] == "25 euro"


def test_a_transcript_only_job_writes_no_notes_files(tmp_path):
    job = Job(tmp_path / "job")
    worker.write_outputs(job, worker.label_speakers(segs("Hi.")), None, {}, raw=None)
    assert [o["name"] for o in job.outputs] == ["transcript.md", "transcript.srt", "transcript.vtt", "meeting.json"]


def test_times_read_as_minutes_and_seconds_and_hours_when_long():
    assert worker.mmss(65) == "01:05" and worker.mmss(3725) == "1:02:05"
    assert worker.srt_time(3725.5) == "01:02:05,500"


def local_worker(tmp_path):
    return worker.Worker({"options": {"distro": "local"}, "launch_dir": str(tmp_path)}, log=lambda *_: None)


def test_a_local_step_runs_as_a_child_process_and_returns_its_last_json_line(tmp_path):
    w = local_worker(tmp_path)
    assert w.local and not (tmp_path / "meeting-watchdog.sh").exists()  # no WSL, so no watchdog script
    result = w.wsl("echo noise; echo '{\"ok\": true, \"seconds\": 1.5}'")
    assert result == {"ok": True, "seconds": 1.5}
    with pytest.raises(RuntimeError, match="the model is missing"):
        w.wsl("echo '{\"ok\": false, \"error\": \"the model is missing\"}'; exit 1")
    with pytest.raises(RuntimeError, match="a speech step failed"):
        w.wsl("echo not json")


def test_cancelling_a_local_step_ends_its_whole_process_group(tmp_path):
    w = local_worker(tmp_path)
    marker = tmp_path / "child.pid"
    job = Job(tmp_path / "job")
    # A shell that starts a grandchild, as a Python step starts helpers; cancel as soon as the grandchild is up.
    command = f"sleep 30 & echo $! > {marker}; wait"

    def cancel_when_started():
        for _ in range(100):
            if marker.exists() and marker.read_text().strip():
                job.cancel_requested = True
                return
            time.sleep(0.05)

    threading.Thread(target=cancel_when_started, daemon=True).start()
    with pytest.raises(worker.JobCancelled):
        w.wsl(command, job)
    pid = int(marker.read_text())
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the step's helper process was left running")


def test_the_mac_engine_chains_speaker_turns_into_recognition(tmp_path, monkeypatch):
    w = worker.Worker({"options": {"distro": "local", "engine": "mlx", "python": "/py", "segmentation_model": "/seg.onnx",
                                   "embedding_model": "/emb.onnx", "asr_model": "/asr", "diar_threshold": 0.35},
                       "launch_dir": str(tmp_path)}, log=lambda *_: None)
    seen = []

    def fake(command, job=None, timeout=7200):
        seen.append(command)
        if " mlxturns " in command:
            (tmp_path / "work" / "segments.json").write_text(json.dumps([{"speaker": "0", "start": 0, "end": 2, "text": "Hi."}]))
            return {"ok": True, "seconds": 2.0}
        return {"ok": True, "seconds": 1.0, "speakers": 3}

    monkeypatch.setattr(w, "wsl", fake)
    (tmp_path / "work").mkdir()
    job = Job(tmp_path / "job")
    segs, stats = w.transcribe(tmp_path / "work" / "audio.wav", tmp_path / "work", "Anna, Ben", job)
    assert segs[0]["text"] == "Hi." and stats == {"diarize_seconds": 1.0, "transcribe_seconds": 2.0}
    assert " sherpa " in seen[0] and "'/seg.onnx' '/emb.onnx' '0.35'" in seen[0]
    assert " mlxturns " in seen[1] and "'/asr' 'Anna, Ben'" in seen[1]
    assert job.progress == ["Working out who spoke when", "Transcribing 3 speakers"]


def test_notes_ask_the_model_not_to_think_and_a_failed_notes_step_keeps_the_transcript(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(worker, "chat", lambda model, prompt, max_tokens, thinking=True: asked.append(thinking) or "not json")

    class Stub:
        options = {}
        gpus = [0]

        def wsl(self, *args, **kwargs):
            return {"ok": True}

        def transcribe(self, audio, work, terms, job):
            return [{"speaker": "a", "start": 0.0, "end": 4.0, "text": "Hello there."}], {}

    class NeedJob(Job):
        def need(self, name, value):
            return {"base_url": "http://127.0.0.1:1", "model": "m", "name": "Test model"}

    job = NeedJob(tmp_path / "job")
    (tmp_path / "job").mkdir()
    (tmp_path / "rec.m4a").write_bytes(b"x")
    worker.generate(Stub(), {"recording": [{"path": str(tmp_path / "rec.m4a")}], "notes": "notes", "correct": "yes"}, job)
    assert asked and set(asked) == {False}  # correction and notes both ask for no thinking
    assert "could not be read" in job.details["notes_error"]
    names = [o["name"] for o in job.outputs]
    assert "transcript.md" in names and "transcript-raw.json" in names and "notes.md" not in names


VTT = """WEBVTT

1
00:00:05.000 --> 00:00:08.000
Anna Lee: Let's start with the budget.

2
00:00:08.500 --> 00:00:10.000
Anna Lee: GPU costs are over.

3
00:00:10.500 --> 00:00:12.000
<v Ben Cho>I'll send the breakdown Friday.</v>
"""


def test_the_form_takes_a_transcript_as_well_as_a_recording():
    upload = {"t1": {"id": "t1", "kind": "transcript", "mime": "text/vtt", "name": "call.vtt", "bytes": 10}}
    assert validate_inputs(PLUGIN, {"mode": "notes", "recording": ["t1"]}, upload.get)["recording"]


def test_a_vtt_keeps_its_names_merges_a_speakers_cues_and_starts_at_zero():
    turns, timed = meeting_transcript.parse(VTT)
    assert timed
    assert [(t["speaker"], t["start"], t["end"]) for t in turns] == [("Anna Lee", 0.0, 5.0), ("Ben Cho", 5.5, 7.0)]
    assert turns[0]["text"] == "Let's start with the budget. GPU costs are over."


def test_a_zoom_text_export_reads_name_and_time_headers():
    turns, timed = meeting_transcript.parse("[Anna Lee] 10:00:05\nHello all.\n\n[Ben Cho] 10:00:20\nHi.\nGood to be here.\n")
    assert timed and [(t["speaker"], t["start"], t["text"]) for t in turns] == [
        ("Anna Lee", 0.0, "Hello all."), ("Ben Cho", 15.0, "Hi. Good to be here.")]


def test_dialogue_lines_with_and_without_times_and_continuation_lines():
    turns, timed = meeting_transcript.parse("[00:01] Anna: First point\nand more.\n[00:09] Ben: Agreed\n")
    assert timed and [(t["speaker"], t["start"], t["text"]) for t in turns] == [
        ("Anna", 0.0, "First point and more."), ("Ben", 8.0, "Agreed")]
    turns, timed = meeting_transcript.parse("Anna: One\nBen: Two\nAnna: Three\n")
    assert not timed and [t["speaker"] for t in turns] == ["Anna", "Ben", "Anna"]


def test_plain_prose_is_one_untimed_speaker_and_an_ordinary_colon_does_not_make_a_speaker():
    turns, timed = meeting_transcript.parse("We met on Monday. Note: nothing was decided.\n\nSecond paragraph here.\n")
    assert not timed and [t["speaker"] for t in turns] == ["Speaker 1", "Speaker 1"] and len(turns) == 2


@pytest.mark.parametrize("text", ["", "   \n\n", "WEBVTT\n"])
def test_an_empty_transcript_is_refused(text):
    with pytest.raises(meeting_transcript.TranscriptError):
        meeting_transcript.parse(text)


def test_a_transcript_job_skips_the_audio_and_an_untimed_one_writes_no_captions(tmp_path, monkeypatch):
    path = tmp_path / "call.txt"
    path.write_text("Anna: Ship it Friday.\nBen: Agreed.\n", encoding="utf-8")
    job = Job(tmp_path / "job")
    job.need = lambda *a, **k: {"error": "no model"}
    ran = []
    stub = type("W", (), {"options": {}, "gpus": [0], "wsl": lambda *a, **k: ran.append("wsl"),
                          "transcribe": lambda *a, **k: ran.append("asr")})()
    worker.generate(stub, {"recording": [{"kind": "transcript", "path": str(path), "original": "call.txt"}], "notes": "transcript"}, job)
    assert ran == [] and job.details["engine"] == "transcript" and job.details["timed"] is False
    names = [o["name"] for o in job.outputs]
    assert "transcript.md" in names and "transcript.srt" not in names and "transcript.vtt" not in names
    assert "[" not in (job.dir / "transcript.md").read_text()
    assert "**Anna:** Ship it Friday." in (job.dir / "transcript.md").read_text()


def test_a_named_speaker_is_not_given_the_same_name_again(tmp_path, monkeypatch):
    path = tmp_path / "call.txt"
    path.write_text("Anna: Ship it Friday.\nBen: Agreed.\n", encoding="utf-8")
    monkeypatch.setattr(worker, "extract", lambda model, segs, people: {
        "summary": ["Ship Friday."], "actions": [], "decisions": [], "speakers": {"Anna": "Anna", "Ben": "Ben Cho"}})
    job = Job(tmp_path / "job")
    job.need = lambda *a, **k: dict(MODEL, name="m")
    stub = type("W", (), {"options": {}, "gpus": [0]})()
    worker.generate(stub, {"recording": [{"kind": "transcript", "path": str(path), "original": "call.txt"}],
                           "notes": "notes", "correct": "no"}, job)
    text = (job.dir / "transcript.md").read_text()
    assert "**Anna:**" in text and "**Ben (Ben Cho):**" in text


def test_a_model_that_always_thinks_is_asked_for_its_lowest_level_and_others_for_none(monkeypatch):
    sent = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices": [{"message": {"content": "ok"}}]}'

    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda request, timeout=0: (sent.append(json.loads(request.data)), Response())[1])
    worker.chat(dict(MODEL, thinking_floor="minimal"), "p", 10, thinking=False)
    worker.chat(MODEL, "p", 10, thinking=False)
    assert sent[0]["reasoning_effort"] == "minimal" and "enable_thinking" not in sent[0]
    assert sent[1]["reasoning_effort"] == "none" and sent[1]["enable_thinking"] is False


def test_a_hint_said_back_by_the_speech_model_is_recognised_but_real_speech_is_not():
    import meeting_pipeline
    terms = ["Apollo", "ACME", "sprint review", "Initech"]
    assert meeting_pipeline.echoes_hotwords("Apollo, ACME, sprint review, Initech.", terms)
    assert meeting_pipeline.echoes_hotwords("ACME, Initech", terms)
    assert not meeting_pipeline.echoes_hotwords("The sprint review went well, Initech.", terms)
    assert not meeting_pipeline.echoes_hotwords("Initech.", terms)


def test_notes_from_a_model_that_always_thinks_get_a_larger_token_budget(monkeypatch):
    budgets = []
    reply = '{"speakers": {}, "summary": ["a"], "actions": [], "decisions": []}'
    monkeypatch.setattr(worker, "chat", lambda model, prompt, max_tokens, thinking=True: (budgets.append(max_tokens), reply)[1])
    worker.extract(MODEL, segs("hi"), "")
    worker.extract(dict(MODEL, thinking_floor="minimal"), segs("hi"), "")
    assert budgets == [8000, 16000]


@pytest.mark.parametrize("tag, name", [
    ("Dana Park| Platform Tea...", "Dana Park"), ("Mira Voss (she/her) | ...", "Mira Voss"), ("Mira Voss I", "Mira Voss"),
    ("Dana Park / Platform Team / Product Manager", "Dana Park"), ("Dana Park  Platform Tea...", "Dana Park"),
    ("Theo Hale | ACME Core |ioS", "Theo Hale"), ("Dr. Ana-Maria O'Neil | x", "Dr. Ana-Maria O'Neil"),
    ("Jonas Reed", "Jonas Reed"), ("Aug27", None), ("27", None), ("Labs1.PNG", None), ("Unmute", None)])
def test_a_name_tag_is_reduced_to_the_persons_name(tag, name):
    import meeting_pipeline
    assert meeting_pipeline.clean_name(tag) == name


def test_names_are_voted_per_speaker_and_text_that_stays_on_screen_is_ignored():
    import meeting_pipeline
    seen = {"0": [["Jonas Reed", "Thu"]] * 8 + [["Thu"]] * 2, "1": [["Dana Park", "Thu"]] * 7 + [[], ["Dana Park"]],
            "2": [["Thu"]] * 5 + [["Mira Voss"]], "3": [["Dana Pak"]] * 4, "4": [["Cody"], []]}
    got = meeting_pipeline.choose_names(seen)
    assert {k: v["name"] for k, v in got.items()} == {"0": "Jonas Reed", "1": "Dana Park", "3": "Dana Park"}  # "Dana Pak" is a typo of the same person
    assert "2" not in got and "4" not in got  # only static text; one vote is too few


def test_speakers_named_from_the_video_keep_the_name_and_the_rest_are_numbered_without_gaps():
    raw = [{"speaker": s, "start": i, "end": i + 1, "text": "x"} for i, s in enumerate(["a", "b", "c", "d", "b"])]
    labelled = worker.label_speakers(raw, {"a": "Dana Park", "c": "Dana Park", "d": "Ann Lee"})
    assert [s["speaker"] for s in labelled] == ["Dana Park", "Speaker 1", "Dana Park", "Ann Lee", "Speaker 1"]


def test_a_video_is_read_for_names_which_label_the_speakers_and_reach_the_notes(tmp_path, monkeypatch):
    video = tmp_path / "call.mp4"
    video.write_bytes(b"x")
    raw = [{"speaker": "0", "start": 0, "end": 4, "text": "Ship it Friday."}, {"speaker": "1", "start": 5, "end": 9, "text": "Agreed."}]
    asked = {}
    monkeypatch.setattr(worker, "extract", lambda model, segs, people: (asked.update(people=people), {
        "summary": ["s"], "actions": [], "decisions": [], "speakers": {}})[1])

    class Stub:
        options, gpus = {"engine": "mlx"}, [0]
        wsl = lambda self, *a, **k: {}
        transcribe = lambda self, *a, **k: (raw, {})
        name_tags = lambda self, video_path, segments, job: ({"0": "Dana Park"}, {"name_tag_frames": 8})

    job = Job(tmp_path / "job")
    job.need = lambda *a, **k: dict(MODEL, name="m")
    worker.generate(Stub(), {"recording": [{"kind": "video", "path": str(video), "original": "call.mp4"}], "notes": "notes",
                             "correct": "no", "people": "Ben"}, job)
    text = (job.dir / "transcript.md").read_text()
    assert "**[00:00] Dana Park:**" in text and "**[00:05] Speaker 1:**" in text
    assert job.details["named_from_video"] == 1 and asked["people"] == "Ben, Dana Park"
    job2 = Job(tmp_path / "job2")
    job2.need = job.need
    Stub.name_tags = lambda self, *a: pytest.fail("asked for names though the form said no")
    worker.generate(Stub(), {"recording": [{"kind": "video", "path": str(video), "original": "call.mp4"}], "notes": "transcript",
                             "video_names": "no"}, job2)
    assert "**[00:00] Speaker 1:**" in (job2.dir / "transcript.md").read_text()


def test_a_speaker_with_only_short_turns_still_gets_frames_and_a_missing_space_is_put_back():
    import meeting_pipeline
    turns = [{"start": 187.8, "end": 194.1}, {"start": 2058.7, "end": 2077.7}, {"start": 2078.4, "end": 2080.1},
             {"start": 2082.5, "end": 2083.8}, {"start": 3000.0, "end": 3000.5}]
    times = meeting_pipeline.sample_times(turns, 10)
    assert len(times) >= 5 and times == sorted(times) and all(187 < t < 2084 for t in times)  # the half-second turn is skipped
    assert meeting_pipeline.choose_names({"2": [["IvanCole"], ["Ivan Cole"]]})["2"]["name"] == "Ivan Cole"
    assert meeting_pipeline.choose_names({"2": [["Ann Lee"], []]}) == {}  # one vote is not enough


def meeting_folder(tmp_path):
    folder = tmp_path / "job"
    folder.mkdir()
    segments = [{"speaker": "Speaker 1", "start": 0.0, "end": 4.0, "text": "Welcome all."},
                {"speaker": "Dana Park", "start": 5.0, "end": 9.0, "text": "Ship it Friday."},
                {"speaker": "Speaker 1", "start": 10.0, "end": 14.0, "text": "Agreed."}]
    (folder / "meeting.json").write_text(json.dumps({"speakers": {"Speaker 1": "Sam"}, "segments": segments, "revision": 1,
                                                    "summary": ["s"]}), encoding="utf-8")
    (folder / "notes.md").write_text("# Meeting notes\n", encoding="utf-8")
    return folder


def edit(folder, **payload):
    return PLUGIN.edit_transcript(folder, {"revision": 1, "segments": [], "rename": {}, **payload})



def test_renaming_a_speaker_changes_every_segment_and_the_files(tmp_path):
    folder = meeting_folder(tmp_path)
    assert edit(folder, rename={"Speaker 1": "Ivan Cole"}) == {"revision": 2, "segments": 3}
    record = json.loads((folder / "meeting.json").read_text())
    assert [s["speaker"] for s in record["segments"]] == ["Ivan Cole", "Dana Park", "Ivan Cole"]
    assert record["speakers"] == {} and record["revision"] == 2 and record["edited"] and record["summary"] == ["s"]  # the notes' own guess goes
    assert "**[00:00] Ivan Cole:** Welcome all." in (folder / "transcript.md").read_text()
    assert "Ivan Cole: Agreed." in (folder / "transcript.srt").read_text()
    assert (folder / "transcript.vtt").read_text().startswith("WEBVTT") and (folder / "notes.md").read_text() == "# Meeting notes\n"
    assert not list(folder.glob("*.tmp"))


def test_one_segment_can_change_its_speaker_and_its_words(tmp_path):
    folder = meeting_folder(tmp_path)
    edit(folder, segments=[{"index": 2, "speaker": "Dana Park", "text": "  Agreed,\nthanks. "}])
    segs = json.loads((folder / "meeting.json").read_text())["segments"]
    assert segs[2]["speaker"] == "Dana Park" and segs[2]["text"] == "Agreed, thanks." and segs[0]["speaker"] == "Speaker 1"
    assert json.loads((folder / "meeting.json").read_text())["speakers"] == {"Speaker 1": "Sam"}  # still used by segment 0


def test_a_stale_revision_and_bad_edits_are_refused_without_changing_anything(tmp_path):
    folder = meeting_folder(tmp_path)
    before = (folder / "meeting.json").read_text()
    for payload, status in [({"revision": 7}, 409), ({"rename": {"Nobody": "X"}}, 422), ({"segments": [{"index": 9, "text": "x"}]}, 422),
                            ({"segments": [{"index": 0, "text": "   "}]}, 422), ({"rename": {"Speaker 1": " "}}, 422)]:
        with pytest.raises(Exception) as caught:
            edit(folder, **payload)
        assert caught.value.status == status
    assert (folder / "meeting.json").read_text() == before and not (folder / "transcript.md").exists()
    with pytest.raises(Exception) as caught:
        edit(folder / "missing")
    assert caught.value.status == 404


def test_a_transcript_without_times_is_rewritten_without_captions(tmp_path):
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "meeting.json").write_text(json.dumps({"speakers": {}, "revision": 1,
                                                    "segments": [{"speaker": "Anna", "start": None, "end": None, "text": "Hi."}]}))
    edit(folder, segments=[{"index": 0, "text": "Hello."}])
    assert (folder / "transcript.md").read_text().strip().endswith("**Anna:** Hello.")
    assert not (folder / "transcript.srt").exists()
