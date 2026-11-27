"""Writing down a voice sample: the transcriber is run in the speech model's own environment, one request at a time."""
import json
from pathlib import Path

import pytest

from generationstation.runtimes import parse_catalog
from generationstation.transcribe import TranscribeError, Transcriber
from generationstation.uploads import UploadStore
from tests.test_voices import wav

ROOT = Path(__file__).resolve().parents[2]
CATALOG = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))


@pytest.fixture
def uploads(tmp_path):
    return UploadStore(tmp_path)


def test_a_sample_is_written_down_by_the_models_own_environment(uploads):
    seen = []

    def run(argv, env, timeout):
        seen.append((argv, env, timeout))
        return 'loading...\n{"text": "  Come   in and \\n sit down.  "}\n'

    upload = uploads.save("me.wav", [wav()])
    text = Transcriber(CATALOG, uploads, run).transcribe("qwen3_tts", upload["id"])
    assert text == "Come in and sit down."
    argv, env, _ = seen[0]
    assert argv[0] == CATALOG.runtimes["qwen3_tts"].python and argv[1].endswith("transcribe_cli.py")
    assert argv[2].endswith("Qwen3-ASR-1.7B-8bit") and argv[3] == str(uploads.root / uploads.get(upload["id"])["file"]) and argv[4] == "English"
    assert "workers" in env["PYTHONPATH"]


def test_a_model_without_a_transcriber_or_a_bad_sample_is_refused(uploads):
    upload = uploads.save("me.wav", [wav()])
    tool = Transcriber(CATALOG, uploads, lambda *args: '{"text": "x"}')
    with pytest.raises(TranscribeError, match="no transcriber"):
        tool.transcribe("yue2", upload["id"])  # a music model
    with pytest.raises(LookupError):
        tool.transcribe("nothing", upload["id"])
    with pytest.raises(TranscribeError, match="not found"):
        tool.transcribe("qwen3_tts", "0" * 32)
    picture = uploads.save("a.png", [b"\x89PNG\r\n\x1a\n" + b"0" * 20])
    with pytest.raises(TranscribeError, match="not found"):
        tool.transcribe("qwen3_tts", picture["id"])
    for output in ("", "not json", '{"error": "boom"}'):
        with pytest.raises(TranscribeError):
            Transcriber(CATALOG, uploads, lambda *args, out=output: out).transcribe("qwen3_tts", upload["id"])
