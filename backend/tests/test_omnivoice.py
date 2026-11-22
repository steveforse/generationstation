"""OmniVoice plugin: catalog entry, its two tabs and their rules (no model is loaded)."""
import json
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, parse_catalog, resolve_settings, validate_inputs

OMNI = get_plugin("omnivoice")
ROOT = Path(__file__).resolve().parents[2]


def test_example_entry_runs_on_the_4080_by_default(tmp_path):
    runtime = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text())).runtimes["omnivoice"]
    preset = runtime.presets["omnivoice"]
    assert preset.gpus == [1] and preset.allowed_gpus == [0, 1]
    values, gpus = resolve_settings(OMNI, preset, {}, [1])
    spec = OMNI.launch(runtime, preset, values, gpus, {"PATH": "C:/Windows"}, tmp_path)
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "1"
    assert OMNI.script_path(runtime).name == "omnivoice_worker.py" and OMNI.script_path(runtime).is_file()


def test_tabs_and_rules():
    uploads = {"a" * 32: {"kind": "audio", "name": "me.wav"}, "b" * 32: {"kind": "image", "name": "me.png"}}
    design = validate_inputs(OMNI, {"mode": "design", "prompt": "Hello there."})
    assert design == {"mode": "design", "gender": "any", "age": "any", "pitch": "any", "accent": "any",
                      "whisper": "no", "prompt": "Hello there.", "speed": "normal", "quality": "standard"}
    clone = validate_inputs(OMNI, {"mode": "clone", "prompt": "Hi.", "sample": ["a" * 32]}, uploads.get)
    assert clone["sample"] == ["a" * 32]
    for inputs, message in [
        ({"mode": "clone", "prompt": "Hi."}, "Add a voice sample"),
        ({"mode": "clone", "prompt": "Hi.", "sample": ["b" * 32]}, "only audio"),
        ({"mode": "design", "prompt": "x" * 5001}, "too long"),
        ({"mode": "design", "prompt": "Hi.", "sample": ["a" * 32]}, "not an input"),
        ({"mode": "design", "prompt": "Hi.", "voice": "warm"}, "not an input"),
        ({"mode": "design", "prompt": "Hi.", "accent": "scottish accent"}, "must be one of"),
        ({"mode": "design", "prompt": "Well [giggle] maybe [laugh]."}, r"\[giggle\], \[laugh\] is not a sound"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(OMNI, inputs, uploads.get)


def test_button_and_result_names():
    assert (OMNI.make_label, OMNI.result_noun) == ("Make speech", "recording")


def test_every_trait_is_one_omnivoice_accepts():
    from generationstation.plugins.omnivoice import instruct

    accepted = {"american accent", "australian accent", "british accent", "canadian accent", "child", "chinese accent",
                "elderly", "female", "high pitch", "indian accent", "japanese accent", "korean accent", "low pitch",
                "male", "middle-aged", "moderate pitch", "portuguese accent", "russian accent", "teenager",
                "very high pitch", "very low pitch", "whisper", "young adult"}  # OmniVoice's own list (its error text)
    design = OMNI.modes["design"].inputs
    offered = {option for key in ("gender", "age", "pitch", "accent") for option in design[key].options} - {"any"}
    assert offered <= accepted and accepted - offered == {"whisper"}
    assert instruct({"gender": "female", "age": "young adult", "pitch": "any", "accent": "british accent",
                     "whisper": "yes"}) == "female, young adult, british accent, whisper"


def test_brackets_allow_only_known_sounds_and_phonemes():
    from generationstation.plugins.omnivoice import bracket_problems

    assert bracket_problems("Oh [laughter] and [B EY1 S] [surprise-oh] [AH0 N]") == []
    assert bracket_problems("[Laughter] [b ey1 s] [cough] [cough]") == ["[Laughter]", "[b ey1 s]", "[cough]"]
    assert all(": " in tip for tip in OMNI.modes["design"].inputs["prompt"].guide)
