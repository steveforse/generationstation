"""The Apple-silicon catalog template: every entry parses, uses a worker file that exists, and no two share a port."""
import json
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import parse_catalog, validate_inputs

ROOT = Path(__file__).resolve().parents[2]
CATALOG = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))


def test_ports_are_unique():
    ports = [entry.port for entry in CATALOG.runtimes.values()]
    assert len(ports) == len(set(ports))


@pytest.mark.parametrize("model_id", sorted(CATALOG.runtimes))
def test_entry_resolves_to_a_worker_or_server_and_one_memory_pool(model_id):
    entry = CATALOG.runtimes[model_id]
    plugin = get_plugin(entry.kind)
    assert plugin is not None
    if hasattr(plugin, "script_path"):
        assert plugin.script_path(entry).is_file()
    for key, preset in entry.presets.items():
        assert preset.gpus == [0] and preset.allowed_gpus == [0], key


def test_new_speech_forms_accept_their_modes():
    s2 = validate_inputs(get_plugin("fish_s2"), {"mode": "speak", "prompt": "[whisper] Hello."})
    assert s2["prompt"] == "[whisper] Hello."
    breeze = validate_inputs(get_plugin("breeze_tts"), {"mode": "design", "prompt": "Hello.", "voice": "A calm woman"})
    assert breeze["voice"] == "A calm woman"
