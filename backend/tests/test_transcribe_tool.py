"""The one `transcribe` chat tool: which running model it picks, how it fills their fields, what it leaves out."""
import json
import wave
from pathlib import Path

import pytest

from generationstation.chat import ChatManager
from generationstation.runtimes import parse_catalog, validate_inputs
from generationstation.transcribe_tool import TranscribeTool
from generationstation.uploads import UploadStore
from tests.test_chat import Generation, Store

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))


def running(*model_ids):
    return [(model_id, MAC.runtimes[model_id], MAC.plugin(model_id)) for model_id in model_ids]


def test_the_description_lists_each_running_model_and_what_it_takes():
    schema = TranscribeTool().schema(running("whisper_asr", "parakeet_asr"))
    text = schema["function"]["description"]
    assert "With times." in text and "No times." not in text
    assert "Takes: a language, words to expect, who spoke." in text and "Takes: who spoke." in text
    assert schema["function"]["parameters"]["required"] == ["recording"]
    assert schema["function"]["parameters"]["properties"]["model"]["enum"] == ["whisper_asr", "parakeet_asr"]
    assert "model" not in TranscribeTool().schema(running("whisper_asr"))["function"]["parameters"]["properties"]
    assert TranscribeTool().schema([]) is None


def test_the_most_accurate_model_that_takes_what_was_asked_is_picked_and_the_rest_is_left_out_in_words():
    tool = TranscribeTool()
    pool = running("parakeet_asr", "whisper_asr", "qwen3_asr")
    model_id, _, _, mode, inputs, refs, notes = tool.plan({"recording": "1a2b3c4d", "terms": "Priya"}, pool)
    assert (model_id, mode, inputs, refs, notes) == ("qwen3_asr", "", {"terms": "Priya"}, {"recording": ["1a2b3c4d"]}, [])
    model_id, *_, inputs, _, _ = tool.plan({"recording": "1a2b3c4d", "language": "french"}, pool)
    assert model_id == "qwen3_asr" and inputs == {"language": "French"}
    model_id, *_, inputs, _, _ = tool.plan({"recording": "1a2b3c4d", "language": "french"}, running("parakeet_asr", "whisper_asr"))
    assert model_id == "whisper_asr" and inputs == {"language": "French"}  # Parakeet has no language field, so the order does not decide
    _, _, _, _, inputs, _, notes = tool.plan({"recording": "1a2b3c4d", "language": "French", "terms": "Priya", "model": "parakeet_asr"}, pool)
    assert inputs == {} and any("language" in note for note in notes) and any("words to expect" in note for note in notes)
    _, _, _, _, inputs, _, notes = tool.plan({"recording": "1a2b3c4d", "language": "Klingon", "model": "whisper_asr"}, pool)
    assert inputs == {} and any("Klingon" in note for note in notes)


def test_who_spoke_is_a_yes_the_form_takes(tmp_path):
    _, runtime, plugin, _, inputs, _, _ = TranscribeTool().plan({"recording": "1a2b3c4d", "speakers": True, "model": "whisper_asr"}, running("whisper_asr"))
    assert inputs == {"speakers": "yes"}
    uploads = UploadStore(tmp_path)
    with wave.open(str(tmp_path / "talk.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * 1600)
    clip = uploads.save("talk.wav", [(tmp_path / "talk.wav").read_bytes()])
    assert validate_inputs(plugin, {**inputs, "recording": [clip["id"]]}, uploads.get, runtime)["speakers"] == "yes"


def test_a_missing_or_wrong_request_is_refused():
    tool = TranscribeTool()
    with pytest.raises(ValueError, match="in `recording`"):
        tool.plan({"recording": " "}, running("whisper_asr"))
    with pytest.raises(ValueError, match="is not running"):
        tool.plan({"recording": "1a2b3c4d", "model": "parakeet_asr"}, running("whisper_asr"))


def test_the_chat_offers_one_transcribe_tool_and_starts_a_job_on_the_picked_model(tmp_path):
    store = Store()
    store.states = {model_id: {"state": "ready"} for model_id in ("whisper_asr", "qwen3_asr")}
    chat = ChatManager(store, MAC, Generation(store, tmp_path / "jobs"), UploadStore(tmp_path))
    tools, handlers = chat._tools()
    assert [tool["function"]["name"] for tool in tools] == ["transcribe"]
    result = chat._call({"name": "transcribe", "arguments": json.dumps({"recording": "ffffffff"})}, handlers)
    assert result["text"].startswith("Not started: There is no finished result ffffffff")
    assert "Used from the **Transcribe** page" in chat._model_guide()
