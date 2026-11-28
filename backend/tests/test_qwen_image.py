"""Qwen Image plugin: catalog entry, form, launch config and capacity estimate (no model is loaded)."""
import json
import sys
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, parse_catalog, resolve_settings, validate_inputs

QWEN = get_plugin("qwen_image")
ROOT = Path(__file__).resolve().parents[2]


def qwen_catalog(tmp_path):
    return parse_catalog({"runtimes": {"qwen_image": {
        "kind": "qwen_image", "name": "Qwen Image pictures", "workload": "image", "port": 8180,
        "python": sys.executable, "output_dir": str(tmp_path), "default_preset": "uncensored",
        "presets": {"uncensored": {
            "name": "Qwen Image 2.1 Uncensored", "gpus": [0], "allowed_gpus": [0, 1],
            "options": {"pipeline_dir": "D:/ai/models/qwen-image-2.1/turbo", "transformer_format": "comfy_nvfp4",
                        "transformer": "D:/ai/models/qwen-image-2.1/uncensored/x-NVFP4-comfy.safetensors"},
            "settings": {"compile": True, "text_encoder_device": "cpu"},
            "estimate": {"ram_gib": 24, "gpu_min_free_gib": {"0": 16, "1": 14}},
        }},
    }}})


def test_form_defaults_and_refusals():
    values = validate_inputs(QWEN, {"prompt": "  a fox reading a map  "})
    assert values == {"prompt": "a fox reading a map", "size": "square", "quality": "quick"}
    for inputs, message in [
        ({"size": "square"}, "Description is required"),
        ({"prompt": "x", "size": "4096x4096"}, "must be one of"),
        ({"prompt": "x", "quality": "ultra"}, "must be one of"),
        ({"prompt": "x" * 2001}, "too long"),
        ({"prompt": "x", "transformer": "C:/evil.safetensors"}, "not an input"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(QWEN, inputs)


def test_one_card_and_worker_config(tmp_path):
    runtime = qwen_catalog(tmp_path).runtimes["qwen_image"]
    preset = runtime.presets["uncensored"]
    with pytest.raises(SettingsError, match="1 GPU at a time"):
        resolve_settings(QWEN, preset, {}, [0, 1])
    with pytest.raises(SettingsError, match="must be one of"):
        resolve_settings(QWEN, preset, {"text_encoder_device": "tpu"}, [1])
    values, gpus = resolve_settings(QWEN, preset, {"compile": False}, [1])
    spec = QWEN.launch(runtime, preset, values, gpus, {"PATH": "C:/Windows"}, tmp_path)
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "1"
    config = json.loads(spec.files["worker-config.json"])
    assert config["settings"] == {"compile": False, "text_encoder_device": "cpu"}
    assert config["options"]["transformer_format"] == "comfy_nvfp4" and config["port"] == 8180
    assert QWEN.script_path(runtime).name == "qwen_image_worker.py" and QWEN.script_path(runtime).is_file()


def test_text_encoder_on_the_card_moves_the_estimate_from_ram_to_vram(tmp_path):
    preset = qwen_catalog(tmp_path).runtimes["qwen_image"].presets["uncensored"]
    assert QWEN.estimate(None, preset, {"text_encoder_device": "cpu"}, [1]) == (24, {1: 14})
    assert QWEN.estimate(None, preset, {"text_encoder_device": "cuda"}, [0]) == (8, {0: 32})


def test_example_catalog_entry_is_valid():
    catalog = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text()))
    entry = catalog.runtimes["qwen_image"]
    assert set(entry.presets) == {"uncensored", "turbo"}
    assert entry.presets["turbo"].options["turbo"] is True


def test_mac_entries_are_one_per_model_and_use_the_mflux_worker():
    catalog = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))
    expected = {"qwen_image": {"mlx", "qwen21"}, "qwen_image_2512": {"qwen2512"}, "z_image": {"zimage"}}
    for model_id, presets in expected.items():
        entry = catalog.runtimes[model_id]
        assert set(entry.presets) == presets and entry.default_preset in presets
        assert QWEN.script_path(entry) == ROOT / "workers" / "qwen_image_mflux_worker.py"
        assert all(p.allowed_gpus == [0] for p in entry.presets.values())
    assert QWEN.estimate(catalog.runtimes["qwen_image"], catalog.runtimes["qwen_image"].presets["mlx"], {}, [0]) == (30, {})  # the model stays loaded, so a start asks for its peak


def test_mflux_worker_sizes_follow_the_shapes_and_snap_to_sixteen(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "workers"))
    import qwen_image_mflux_worker as worker

    assert worker._size("portrait") == (768, 1152) and worker._size(None) == (1024, 1024)
    assert worker._size("1000x700") == (992, 688)
    with pytest.raises(ValueError, match="between 256 and 2048"):
        worker._size("4096x512")
