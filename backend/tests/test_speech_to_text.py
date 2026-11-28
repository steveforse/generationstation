"""Speech to text: the declarations of the three models, the transcript files, and the worker around a stand-in model (no mlx needed)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import describe_runtime, parse_catalog

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
import transcribe_mlx_worker as worker
import transcript_files

MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))
KINDS = ["qwen3_asr", "whisper_asr", "parakeet_asr"]


@pytest.mark.parametrize("kind", KINDS)
def test_each_plugin_declares_capabilities_that_match_its_fields(kind):
    plugin = get_plugin(kind)
    assert plugin.transcribe is not None and plugin.transcribe.check(plugin) == []


def info(model_id):
    return describe_runtime(model_id, MAC.runtimes[model_id], [])["generation"]["transcribe"]


def test_the_roles_say_what_each_model_takes():
    assert set(info("qwen3_asr")["roles"][""]) == {"recording", "language", "terms", "speakers"}
    assert set(info("whisper_asr")["roles"][""]) == {"recording", "language", "terms", "speakers"}
    assert set(info("parakeet_asr")["roles"][""]) == {"recording", "speakers"}  # it detects the language and takes no word list
    assert info("qwen3_asr")["times"] == "lines" and info("parakeet_asr")["times"] == "lines"


def test_who_spoke_needs_speaker_detection_unless_the_model_labels_speakers_itself():
    raw = json.loads((ROOT / "runtimes.mac.example.json").read_text())
    for key in ("qwen3_asr", "whisper_asr", "parakeet_asr"):
        for preset in raw["runtimes"][key]["presets"].values():
            for option in ("segmentation_model", "embedding_model", "diar_python"):
                preset["options"].pop(option, None)
    bare = parse_catalog(raw)
    for key in ("qwen3_asr", "whisper_asr", "parakeet_asr"):
        generation = describe_runtime(key, bare.runtimes[key], [])["generation"]
        assert "speakers" not in {field["key"] for field in generation["inputs"]}
        assert generation["transcribe"]["speakers"] == "none" and "speakers" not in generation["transcribe"]["roles"][""]


# ----- the transcript files ------------------------------------------------------------------------------------

def test_a_transcript_with_times_and_speakers_has_captions():
    segments = transcript_files.name_speakers([{"speaker": 7, "start": 0, "end": 2.5, "text": "Hello there."}, {"speaker": 3, "start": 3, "end": 4, "text": "Hi."}])
    files = transcript_files.render(segments)
    assert files["transcript.md"] == "# Transcript\n\n**[00:00] Speaker 1:** Hello there.\n\n**[00:03] Speaker 2:** Hi.\n"
    assert files["transcript.txt"] == "[00:00] Speaker 1: Hello there.\n[00:03] Speaker 2: Hi.\n"
    assert "00:00:00,000 --> 00:00:02,500\nSpeaker 1: Hello there." in files["transcript.srt"]
    assert files["transcript.vtt"].startswith("WEBVTT\n") and "00:00:03.000 --> 00:00:04.000" in files["transcript.vtt"]


def test_a_transcript_without_times_is_paragraphs_and_has_no_captions():
    files = transcript_files.render([{"text": "One. Two. Three. Four. Five."}])
    assert files["transcript.md"] == "# Transcript\n\nOne. Two. Three. Four.\n\nFive.\n" and set(files) == {"transcript.md", "transcript.txt"}


def test_speakers_are_laid_over_timed_lines_by_overlap_and_neighbours_join():
    lines = [{"start": 0, "end": 4, "text": "a"}, {"start": 4, "end": 8, "text": "b"}, {"start": 8, "end": 12, "text": "c"}, {"start": 40, "end": 41, "text": "d"}]
    turns = [{"speaker": "s0", "start": 0, "end": 9}, {"speaker": "s1", "start": 9, "end": 13}]
    got = transcript_files.merge_same_speaker(transcript_files.name_speakers(transcript_files.assign_speakers(lines, turns)))
    assert [(g["speaker"], g["text"]) for g in got] == [("Speaker 1", "a b"), ("Speaker 2", "c"), ("Speaker 2", "d")]  # d is in no turn (the previous speaker's) and too late to join c


# ----- the worker, with a stand-in model ------------------------------------------------------------------------

class Job:
    def __init__(self, folder):
        self.folder, self.cancel_requested, self.reports, self.details = folder, False, [], {}

    def output(self, name, mime):
        return Path(self.folder) / name

    def report(self, text):
        self.reports.append(text)

    def detail(self, **values):
        self.details.update(values)


class Thread:
    def call(self, task):
        return task()


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "talk.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", str(path)], check=True)
    return path


def run(engine, model, recording, tmp_path, **inputs):
    out = tmp_path / "out"
    out.mkdir()
    job = Job(out)
    state = {"engine": engine, "model": model, "thread": Thread(), "options": {}}
    worker.generate(state, {"recording": [{"path": str(recording)}], **inputs}, job)
    return job, {path.name: path.read_text() for path in out.iterdir()}


def test_whisper_lines_with_times_become_captions_and_the_words_to_expect_are_its_prompt(recording, tmp_path):
    seen = {}

    def generate(path, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(text="Hello. Bye.", language="fr", segments=[{"start": 0.0, "end": 1.0, "text": " Hello."}, {"start": 1.0, "end": 2.0, "text": " Bye."}])

    job, files = run("whisper", SimpleNamespace(generate=generate), recording, tmp_path, language="French", terms="Zephyrine,\nPriya")
    assert seen == {"language": "fr", "initial_prompt": "Zephyrine, Priya"}
    assert set(files) == {"transcript.md", "transcript.txt", "transcript.srt", "transcript.vtt", "transcript.json"}
    record = json.loads(files["transcript.json"])
    assert record["language"] == "fr" and record["text"] == "Hello. Bye." and record["terms"] == ["Zephyrine", "Priya"]
    assert job.details["times"] == "yes" and job.details["words"] == 2


def test_parakeet_sentences_are_the_lines(recording, tmp_path):
    sentences = [SimpleNamespace(start=0.0, end=1.5, text=" One."), SimpleNamespace(start=1.5, end=3.0, text=" Two.")]
    _, files = run("parakeet", SimpleNamespace(generate=lambda path, **kw: SimpleNamespace(text="One. Two.", sentences=sentences)), recording, tmp_path)
    assert "**[00:01]** Two." in files["transcript.md"] and "transcript.srt" in files


def test_a_file_that_is_not_sound_is_refused_in_plain_words(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")
    with pytest.raises(ValueError, match="could not be read as audio or video"):
        worker.to_wav(str(bad), tmp_path)
