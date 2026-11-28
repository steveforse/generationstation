"""The one `make_image` chat tool: which running model and tab it picks, how it fills their fields, what it leaves out."""
import json
from pathlib import Path

import pytest

from generationstation.chat import ChatManager
from generationstation.make_image import ImageTool
from generationstation.runtimes import parse_catalog, validate_inputs
from generationstation.uploads import UploadStore
from tests.test_chat import Generation, Store

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))
WINDOWS = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text()))


def running(catalog, *model_ids):
    return [(model_id, catalog.runtimes[model_id], catalog.plugin(model_id)) for model_id in model_ids]


def test_the_description_lists_each_running_model_and_what_it_takes():
    schema = ImageTool().schema(running(MAC, "z_image", "qwen_image_2512"))
    text = schema["function"]["description"]
    assert "Z-Image Turbo" in text and "Qwen-Image 2512" in text and "shape: square, portrait, landscape, wide" in text
    z_line, qwen_line = text.split("- Qwen-Image 2512")[0], text.split("- Qwen-Image 2512")[1]
    assert "negative prompt" in qwen_line and "negative prompt" not in z_line and "quality choice" not in text
    assert "pictures" not in schema["function"]["parameters"]["properties"]  # no running model edits
    assert schema["function"]["parameters"]["properties"]["model"]["enum"] == ["z_image", "qwen_image_2512"]
    assert ImageTool().schema([]) is None
    both = ImageTool().schema(running(WINDOWS, "qwen_image", "minimax_h3"))
    assert "pictures" in both["function"]["parameters"]["properties"] and "can edit the pictures" in both["function"]["description"]


def test_a_description_fills_the_models_own_fields_and_says_what_it_left_out():
    tool = ImageTool()
    model_id, _, plugin, mode, inputs, refs, notes = tool.plan(
        {"prompt": "A fox", "shape": "wide", "quality": "best", "negative_prompt": "blurry", "seed": 5}, running(MAC, "z_image"))
    assert model_id == "z_image" and mode == "" and refs == {}
    assert inputs == {"prompt": "A fox", "size": "wide", "seed": 5}
    assert any("quality" in note for note in notes) and any("avoid" in note for note in notes)
    assert validate_inputs(plugin, inputs, None, MAC.runtimes["z_image"])["size"] == "wide"
    _, _, _, _, inputs, _, notes = tool.plan({"prompt": "A fox", "negative_prompt": "blurry"}, running(MAC, "qwen_image_2512"))
    assert inputs["negative_prompt"] == "blurry" and notes == []


def test_pictures_go_to_a_model_that_edits_and_are_refused_where_none_can():
    tool = ImageTool()
    pool = running(WINDOWS, "qwen_image", "minimax_h3")
    model_id, _, _, mode, inputs, refs, _ = tool.plan({"prompt": "Make picture 1 blue", "pictures": ["1a2b3c4d"]}, pool)
    assert (model_id, mode) == ("minimax_h3", "edit") and inputs["mode"] == "edit" and refs == {"images": ["1a2b3c4d"]}
    model_id, _, _, mode, inputs, _, _ = tool.plan({"prompt": "A fox"}, pool)
    assert model_id == "qwen_image" and "mode" not in inputs
    with pytest.raises(ValueError, match="cannot start from pictures"):
        tool.plan({"prompt": "x", "pictures": ["1a2b3c4d"], "model": "qwen_image"}, pool)
    with pytest.raises(ValueError, match="in `prompt`"):
        tool.plan({"prompt": " "}, pool)
    with pytest.raises(ValueError, match="is not running"):
        tool.plan({"prompt": "x", "model": "z_image"}, pool)


def test_the_chat_offers_one_image_tool_and_keeps_the_video_tabs_of_h3(tmp_path):
    store = Store()
    store.states = {model_id: {"state": "ready"} for model_id in ("qwen_image", "minimax_h3", "yue2")}
    chat = ChatManager(store, WINDOWS, Generation(store, tmp_path / "jobs"), UploadStore(tmp_path))
    tools, handlers = chat._tools()
    names = [tool["function"]["name"] for tool in tools]
    assert "make_image" in names and not any(name.startswith("make_qwen_image") for name in names)
    assert not any(name in names for name in ("make_minimax_h3__picture", "make_minimax_h3__edit"))
    assert "make_video" in names and not any(name.startswith("make_minimax_h3") for name in names)  # its clip tabs go through make_video
    result = chat._call({"name": "make_image", "arguments": json.dumps({"prompt": "A fox", "shape": "wide"})}, handlers)
    assert result["text"].startswith("Started job") and result["job"]["model_id"] == "qwen_image"
    assert "Picture tabs are used from the **Images** page" in chat._model_guide()
