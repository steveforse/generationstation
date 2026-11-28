"""The one `speak` chat tool: which running model and tab it picks, how it fills their fields, what it leaves out."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from generationstation.chat import ChatManager
from generationstation.runtimes import parse_catalog, validate_inputs
from generationstation.speak import SpeakTool
from generationstation.uploads import UploadStore
from generationstation.voices import VoiceLibrary
from tests.test_chat import Generation, Store
from tests.test_voices import wav

ROOT = Path(__file__).resolve().parents[2]
CATALOG = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))


@pytest.fixture
def world(tmp_path):
    uploads, voices = UploadStore(tmp_path), VoiceLibrary(tmp_path)
    record = uploads.get(uploads.save("sample.wav", [wav()])["id"])
    voices.create("Anna", "Come in.", record, uploads.root / record["file"])
    return uploads, voices


def running(*model_ids):
    return [(model_id, CATALOG.runtimes[model_id], CATALOG.plugin(model_id)) for model_id in model_ids]


def test_the_tool_describes_each_running_model_and_the_saved_voices(world):
    _, voices = world
    schema = SpeakTool(voices).schema(running("qwen3_tts", "omnivoice", "fish_s2"))
    text = schema["function"]["description"]
    assert "Qwen3-TTS" in text and "[whisper]" in text and "Anna" in text and "[laughter]" in text
    assert "Do not put [bracketed] cues" in text  # Qwen3-TTS has none
    assert schema["function"]["parameters"]["properties"]["model"]["enum"] == ["qwen3_tts", "omnivoice", "fish_s2"]
    assert SpeakTool(voices).schema([]) is None
    assert "model" not in SpeakTool(voices).schema(running("omnivoice"))["function"]["parameters"]["properties"]


def test_a_saved_voice_goes_to_a_model_that_clones_with_its_sample_and_words(world):
    uploads, voices = world
    tool = SpeakTool(voices)
    model_id, _, inputs, notes = tool.plan({"text": "Hello there.", "voice": "anna"}, running("qwen3_tts"), uploads)
    assert model_id == "qwen3_tts" and inputs["mode"] == "clone" and inputs["sample_text"] == "Come in." and notes == []
    assert uploads.get(inputs["sample"][0])["kind"] == "audio"
    # Every model that takes the inputs accepts them as the form would.
    plugin = CATALOG.plugin("qwen3_tts")
    assert validate_inputs(plugin, inputs, uploads.get, CATALOG.runtimes["qwen3_tts"]) is not None
    with pytest.raises(ValueError, match="no saved voice named 'Zed'"):
        tool.plan({"text": "x", "voice": "Zed"}, running("qwen3_tts"), uploads)


def test_the_model_is_chosen_for_what_was_asked_and_a_clone_is_refused_where_there_is_none(world):
    uploads, voices = world
    tool = SpeakTool(voices)
    # Asked for a described voice, with a built-in-only first model running: the one that can describe is picked.
    model_id, _, inputs, _ = tool.plan({"text": "Hi.", "voice_description": "calm older man"}, running("fish_s2", "omnivoice"), uploads)
    assert model_id == "omnivoice" and inputs["mode"] == "design"
    # A model with no clone source refuses a saved voice and names the running ones that can.
    qwen = CATALOG.plugin("qwen3_tts")
    fixed = SimpleNamespace(modes=qwen.modes, speech=qwen.speech.model_copy(update={"voices": {"builtin": "builtin"}}))
    with pytest.raises(ValueError, match=r"cannot speak in a saved voice. Use S2 Pro"):
        tool.plan({"text": "Hi.", "voice": "Anna", "model": "fixed"}, [("fixed", CATALOG.runtimes["qwen3_tts"], fixed), *running("fish_s2")], uploads)
    with pytest.raises(ValueError, match="is not running"):
        tool.plan({"text": "Hi.", "model": "qwen3_tts"}, running("fish_s2"), uploads)
    with pytest.raises(ValueError, match="in `text`"):
        tool.plan({"text": "  "}, running("fish_s2"), uploads)


def test_roles_fill_each_models_own_fields_and_what_it_cannot_take_is_said(world):
    uploads, voices = world
    tool = SpeakTool(voices)
    _, _, inputs, notes = tool.plan({"text": "Run!", "direction": "Out of breath", "builtin_voice": "Ryan", "seed": 7}, running("qwen3_tts"), uploads)
    assert inputs["mode"] == "builtin" and inputs["prompt"] == "Run!" and inputs["style"] == "Out of breath" and inputs["speaker"] == "Ryan" and inputs["seed"] == 7
    assert notes == []
    # OmniVoice has no direction field: the words go, the direction is reported.
    _, _, inputs, notes = tool.plan({"text": "Run!", "direction": "Out of breath", "voice_description": "young woman"}, running("omnivoice"), uploads)
    assert inputs["prompt"] == "Run!" and "style" not in inputs and any("direction" in note for note in notes)


def test_cues_a_model_would_read_aloud_or_refuse_are_taken_out_of_the_text(world):
    uploads, voices = world
    tool = SpeakTool(voices)
    _, _, inputs, notes = tool.plan({"text": "Fine. [sighs] Come in."}, running("qwen3_tts"), uploads)
    assert inputs["prompt"] == "Fine. Come in." and any("[sighs]" in note for note in notes)
    _, _, inputs, notes = tool.plan({"text": "Ha [laughter] and [whispers] ok.", "voice_description": "man"}, running("omnivoice"), uploads)
    assert inputs["prompt"] == "Ha [laughter] and ok." and any("[whispers]" in note for note in notes)
    _, _, inputs, notes = tool.plan({"text": "[whisper] Closer."}, running("fish_s2"), uploads)
    assert inputs["prompt"] == "[whisper] Closer." and notes == []


def test_the_chat_offers_one_speak_tool_and_not_a_tool_per_speech_model(tmp_path, world):
    uploads, voices = world
    store = Store()
    store.states = {model_id: {"state": "ready"} for model_id in ("qwen3_tts", "omnivoice", "yue2")}
    chat = ChatManager(store, CATALOG, Generation(store, tmp_path / "jobs"), uploads, voices=voices)
    tools, handlers = chat._tools()
    names = [tool["function"]["name"] for tool in tools]
    assert "speak" in names and not any(name.startswith(("make_qwen3_tts", "make_omnivoice")) for name in names)
    assert "make_song" in names
    result = chat._call({"name": "speak", "arguments": json.dumps({"text": "Hello.", "voice": "Anna"})}, handlers)
    assert result["text"].startswith("Started job") and result["job"]["model_id"] == "qwen3_tts"
    assert chat._call({"name": "speak", "arguments": json.dumps({"text": "Hello.", "voice": "Zed"})}, handlers)["text"].startswith("Not started: There is no saved voice")
    assert "Used from the **Speech** page" in chat._model_guide()
