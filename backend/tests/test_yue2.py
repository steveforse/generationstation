"""YuE2 plugin: the Apple-silicon catalog entry."""


def test_mac_entry_uses_the_mlx_worker():
    import json
    from pathlib import Path

    from generationstation.plugins import get_plugin
    from generationstation.runtimes import parse_catalog

    root = Path(__file__).resolve().parents[2]
    entry = parse_catalog(json.loads((root / "runtimes.mac.example.json").read_text())).runtimes["yue2"]
    plugin = get_plugin("yue2")
    assert plugin.script_path(entry) == root / "workers" / "yue2_mlx_worker.py" and plugin.script_path(entry).exists()
    assert entry.presets["mlx"].options["precision"] == "8bit"
