"""The one `make_video` chat tool: which running model and tab it picks, how it fills their fields, what it leaves out."""
import json
from pathlib import Path

import pytest

from generationstation.make_video import VideoTool
from generationstation.runtimes import parse_catalog, validate_inputs

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))


def running(*model_ids):
    return [(model_id, MAC.runtimes[model_id], MAC.plugin(model_id)) for model_id in model_ids]


def test_the_description_lists_each_running_model_and_what_it_takes():
    schema = VideoTool().schema(running("ltx_video", "longcat_video", "fastmetal_video"))
    text = schema["function"]["description"]
    assert "length in seconds: 2, 4, 5" in text and "continue an earlier clip" in text and "sound it makes itself" in text
    properties = schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["prompt"]
    assert {"first_picture", "last_picture", "source_clip"} <= set(properties)
    assert properties["model"]["enum"] == ["ltx_video", "longcat_video", "fastmetal_video"]
    assert "source_clip" not in VideoTool().schema(running("ltx_video"))["function"]["parameters"]["properties"]
    assert VideoTool().schema([]) is None


def test_a_description_fills_the_models_own_fields_with_the_nearest_length_and_shape():
    tool = VideoTool()
    model_id, _, plugin, mode, inputs, refs, notes = tool.plan(
        {"prompt": "a fox", "length": 3.4, "shape": "portrait video", "quality": "sharp", "seed": 5}, running("ltx_video"))
    assert (model_id, mode, refs) == ("ltx_video", "text", {})
    assert inputs == {"mode": "text", "prompt": "a fox", "length": "4 seconds", "shape": "portrait", "quality": "sharp", "seed": 5}
    assert notes == [] and validate_inputs(plugin, inputs, None, MAC.runtimes["ltx_video"])["length"] == "4 seconds"
    _, _, _, mode, inputs, _, notes = tool.plan({"prompt": "a fox", "length": 3, "quality": "sharp", "sounds": "wind"}, running("fastmetal_video"))
    assert mode == "" and "mode" not in inputs and inputs["length"] == "medium"
    assert any("quality" in note for note in notes) and any("sounds" in note for note in notes)


def test_pictures_and_clips_go_to_a_model_that_can_and_the_tab_follows_the_arguments():
    tool = VideoTool()
    pool = running("fastmetal_video", "ltx_video", "longcat_video")
    model_id, _, _, mode, _, refs, _ = tool.plan({"prompt": "it walks", "first_picture": "1a2b3c4d"}, pool)
    assert (model_id, mode, refs) == ("ltx_video", "image", {"image": ["1a2b3c4d"]})
    model_id, _, _, mode, _, refs, _ = tool.plan({"prompt": "it walks", "first_picture": "1a2b3c4d", "last_picture": "5e6f7a8b", "model": "ltx_video"}, pool)
    assert refs == {"image": ["1a2b3c4d"], "last": ["5e6f7a8b"]}
    _, _, _, mode, _, refs, notes = tool.plan({"prompt": "it walks", "first_picture": "1a2b3c4d", "last_picture": "5e6f7a8b", "model": "longcat_video"}, pool)
    assert mode == "image" and refs == {"image": ["1a2b3c4d"]} and any("last picture" in note for note in notes)
    model_id, _, _, mode, _, refs, _ = tool.plan({"prompt": "it runs on", "source_clip": "1a2b3c4d"}, pool)
    assert (model_id, mode, refs) == ("longcat_video", "continue", {"source": ["1a2b3c4d"]})
    with pytest.raises(ValueError, match="cannot continue a clip"):
        tool.plan({"prompt": "x", "source_clip": "1a2b3c4d", "model": "ltx_video"}, pool)
    with pytest.raises(ValueError, match="No running model can start from pictures"):
        tool.plan({"prompt": "x", "first_picture": "1a2b3c4d"}, running("fastmetal_video"))
    with pytest.raises(ValueError, match="not both"):
        tool.plan({"prompt": "x", "first_picture": "1a2b3c4d", "source_clip": "5e6f7a8b"}, pool)
    with pytest.raises(ValueError, match="in `prompt`"):
        tool.plan({"prompt": " "}, pool)
    with pytest.raises(ValueError, match="is not running"):
        tool.plan({"prompt": "x", "model": "longcat_video"}, running("ltx_video"))
