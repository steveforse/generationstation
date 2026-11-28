"""The one `make_song` chat tool: which running model and tab it picks, how it fills their fields, what it leaves out."""
import json
from pathlib import Path

import pytest

from generationstation.make_song import SongTool
from generationstation.runtimes import parse_catalog, validate_inputs

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))


def running(*model_ids):
    return [(model_id, MAC.runtimes[model_id], MAC.plugin(model_id)) for model_id in model_ids]


def test_the_description_lists_each_running_model_and_what_it_takes():
    schema = SongTool().schema(running("yue2", "ace_step", "minimax_music"))
    text = schema["function"]["description"]
    assert "no length setting" in text and "length in seconds: 60, 30, 120" in text and "tempo" in text and "redo a section" in text
    properties = schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["style"] and "source_song" in properties
    assert properties["model"]["enum"] == ["yue2", "ace_step", "minimax_music"]
    assert "source_song" in SongTool().schema(running("yue2"))["function"]["parameters"]["properties"]  # YuE2 makes a new version too
    assert "source_song" not in SongTool().schema(running("minimax_music"))["function"]["parameters"]["properties"]
    assert SongTool().schema([]) is None


def test_a_style_fills_the_models_own_fields_and_says_what_it_left_out():
    tool = SongTool()
    model_id, _, plugin, mode, inputs, refs, notes = tool.plan(
        {"style": "folk", "lyrics": "[Verse]\nla", "length": 100, "tempo": 90, "seed": 5}, running("ace_step"))
    assert (model_id, mode, refs) == ("ace_step", "song", {})
    assert inputs == {"mode": "song", "style": "folk", "lyrics": "[Verse]\nla", "length": "120", "tempo": 90, "seed": 5}  # the nearest length offered
    assert validate_inputs(plugin, inputs, None, MAC.runtimes["ace_step"])["length"] == "120"
    _, _, _, mode, inputs, _, notes = tool.plan({"style": "folk", "length": 60, "tempo": 90, "key": "A minor"}, running("yue2"))
    assert mode == "" and "mode" not in inputs and inputs == {"style": "folk"}
    assert any("length" in note for note in notes) and any("tempo" in note for note in notes) and any("key" in note for note in notes)
    _, _, _, _, inputs, _, notes = tool.plan({"style": "folk", "steps": 10}, running("minimax_music"))
    assert inputs["steps"] == 10 and notes == []


def test_a_song_to_start_from_goes_to_a_model_that_can_and_the_tab_follows_the_arguments():
    tool = SongTool()
    pool = running("minimax_music", "yue2", "ace_step")
    model_id, _, _, mode, inputs, refs, _ = tool.plan({"style": "jazz", "lyrics": "[Verse]\nla", "source_song": "1a2b3c4d"}, pool)
    assert (model_id, mode, refs) == ("yue2", "", {"source": ["1a2b3c4d"]}) and "mode" not in inputs  # the first running model that can
    model_id, _, _, mode, inputs, refs, _ = tool.plan({"style": "jazz", "source_song": "1a2b3c4d", "strength": 30, "model": "ace_step"}, pool)
    assert (model_id, mode, inputs["strength"], refs) == ("ace_step", "cover", 30, {"source": ["1a2b3c4d"]})
    _, _, _, _, inputs, _, notes = tool.plan({"style": "jazz", "source_song": "1a2b3c4d", "strength": 30, "model": "yue2"}, pool)
    assert "strength" not in inputs and any("how closely" in note for note in notes)  # YuE2 has no strength
    _, _, _, mode, inputs, _, notes = tool.plan({"style": "piano", "source_song": "1a2b3c4d", "start": 10, "end": 20, "strength": 30}, pool)
    assert mode == "repaint" and (inputs["start"], inputs["end"]) == (10, 20) and "strength" not in inputs and notes == []  # only ACE redoes a section
    with pytest.raises(ValueError, match="cannot start from a song"):
        tool.plan({"style": "x", "source_song": "1a2b3c4d", "model": "minimax_music"}, pool)
    with pytest.raises(ValueError, match="No running model can start from a song"):
        tool.plan({"style": "x", "source_song": "1a2b3c4d"}, running("minimax_music"))
    with pytest.raises(ValueError, match="in `style`"):
        tool.plan({"style": " "}, pool)
    with pytest.raises(ValueError, match="is not running"):
        tool.plan({"style": "x", "model": "minimax_music"}, running("yue2", "ace_step"))
