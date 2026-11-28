"""The song models' declared capabilities must agree with their own tabs and fields, and narrow per model."""
import json
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import describe_runtime, parse_catalog, validate_inputs
from generationstation.uploads import UploadStore

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))
WINDOWS = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text()))


@pytest.mark.parametrize("kind", ["yue2", "ace_step", "minimax_music"])
def test_each_song_plugin_declares_capabilities_that_match_its_fields(kind):
    plugin = get_plugin(kind)
    assert plugin.music is not None and plugin.music.check(plugin) == []


def roles_of(catalog, model_id):
    return describe_runtime(model_id, catalog.runtimes[model_id], [])["generation"]["music"]["roles"]


def test_the_roles_say_what_each_model_takes():
    assert set(roles_of(MAC, "yue2")[""]) == {"style", "lyrics", "seed", "source"}  # the song is as long as the lyrics: no length; it can start from a song
    assert set(roles_of(MAC, "minimax_music")[""]) == {"style", "lyrics", "length", "steps", "seed"}
    ace = roles_of(MAC, "ace_step")
    assert set(ace) == {"song", "cover", "repaint"} and {"tempo", "key", "time_signature", "length"} <= set(ace["song"])
    assert {"source", "strength"} <= set(ace["cover"]) and {"source", "start", "end"} <= set(ace["repaint"])
    assert set(roles_of(WINDOWS, "yue2")[""]) == {"style", "lyrics", "seed"}


def test_lyrics_are_optional_everywhere_and_the_extra_fields_are_not_in_the_main_form():
    for kind in ("yue2", "ace_step", "minimax_music"):
        plugin = get_plugin(kind)
        for mode, spec in (plugin.modes.items() if plugin.modes else [("", plugin)]):
            assert not (spec.inputs if hasattr(spec, "inputs") else plugin.inputs)["lyrics"].required
    song = get_plugin("ace_step").modes["song"].inputs
    assert not song["tempo"].advanced and song["key"].advanced and song["time_signature"].advanced
    assert get_plugin("minimax_music").inputs["steps"].advanced


def test_new_versions_and_redone_sections_need_a_song_and_the_old_form_still_works(tmp_path):
    plugin, runtime = get_plugin("ace_step"), MAC.runtimes["ace_step"]
    uploads = UploadStore(tmp_path)
    song = uploads.save("song.flac", [b"fLaC" + b"0" * 20])
    old = validate_inputs(plugin, {"style": "folk", "lyrics": "[Verse]\nla", "length": "30"}, uploads.get, runtime)  # no mode: a result from before the tabs
    assert old["length"] == "30"
    cover = validate_inputs(plugin, {"mode": "cover", "style": "jazz", "source": [song["id"]], "strength": 30}, uploads.get, runtime)
    assert cover["strength"] == 30
    redo = validate_inputs(plugin, {"mode": "repaint", "style": "piano", "source": [song["id"]], "start": 10, "end": 20}, uploads.get, runtime)
    assert (redo["start"], redo["end"]) == (10, 20)
    with pytest.raises(Exception, match="Song is required"):
        validate_inputs(plugin, {"mode": "cover", "style": "jazz"}, uploads.get, runtime)
    with pytest.raises(Exception, match="tempo"):
        validate_inputs(plugin, {"mode": "repaint", "style": "piano", "source": [song["id"]], "tempo": 90}, uploads.get, runtime)


def test_yue2_makes_a_new_version_of_a_song_on_the_mac_only(tmp_path):
    plugin, runtime = get_plugin("yue2"), MAC.runtimes["yue2"]
    uploads = UploadStore(tmp_path)
    song = uploads.save("song.flac", [b"fLaC" + b"0" * 20])
    sung = validate_inputs(plugin, {"style": "jazz", "lyrics": "[Verse]\nla", "source": [song["id"]]}, uploads.get, runtime)
    assert sung["source"] == [song["id"]]
    assert validate_inputs(plugin, {"style": "jazz", "source": [song["id"]]}, uploads.get, runtime)["source"] == [song["id"]]  # no lyrics: an instrumental version
    with pytest.raises(Exception, match="cannot be off"):
        validate_inputs(plugin, {"style": "jazz", "lyrics": "[Verse]\nla", "mode": "off", "source": [song["id"]]}, uploads.get, runtime)
    with pytest.raises(Exception, match="source"):  # the Windows worker has no melody reader
        validate_inputs(plugin, {"style": "jazz", "lyrics": "[Verse]\nla", "source": [song["id"]]}, uploads.get, WINDOWS.runtimes["yue2"])
