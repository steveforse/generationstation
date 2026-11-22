"""Qwen3-TTS plugin: catalog entry, its three tabs and their rules (no model is loaded)."""
import json
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, parse_catalog, resolve_settings, validate_inputs

QTTS = get_plugin("qwen3_tts")
ROOT = Path(__file__).resolve().parents[2]


def test_example_entry_and_launch(tmp_path):
    runtime = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text())).runtimes["qwen3_tts"]
    preset = runtime.presets["qwen3_tts"]
    values, gpus = resolve_settings(QTTS, preset, {}, [1])
    spec = QTTS.launch(runtime, preset, values, gpus, {"PATH": "C:/Windows"}, tmp_path)
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "1" and QTTS.script_path(runtime).is_file()
    assert set(preset.options) == {"custom_voice_dir", "voice_design_dir", "base_dir"}


def test_tabs_and_rules():
    uploads = {"a" * 32: {"kind": "audio", "name": "me.wav"}}
    builtin = validate_inputs(QTTS, {"mode": "builtin", "prompt": "Hello.", "style": "Very happy"})
    assert builtin == {"mode": "builtin", "speaker": "Ryan", "prompt": "Hello.", "style": "Very happy", "language": "auto"}
    assert validate_inputs(QTTS, {"mode": "clone", "prompt": "Hi.", "sample": ["a" * 32]}, uploads.get)["sample"]
    for inputs, message in [
        ({"mode": "design", "prompt": "Hi."}, "Voice is required"),
        ({"mode": "clone", "prompt": "Hi."}, "Add a voice sample"),
        ({"mode": "builtin", "prompt": "Hi.", "speaker": "Bob"}, "must be one of"),
        ({"mode": "builtin", "prompt": "Hi.", "language": "klingon"}, "must be one of"),
        ({"mode": "clone", "prompt": "Hi.", "sample": ["a" * 32], "style": "angry"}, "not an input"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(QTTS, inputs, uploads.get)
    assert set(QTTS.modes["builtin"].inputs["speaker"].option_labels) == set(QTTS.modes["builtin"].inputs["speaker"].options)
