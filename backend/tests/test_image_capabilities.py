"""The picture models' declared capabilities must agree with their own tabs and fields, and narrow per model."""
import json
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import describe_runtime, parse_catalog, validate_inputs

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))
WINDOWS = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text()))


@pytest.mark.parametrize("kind", ["qwen_image", "minimax_h3"])
def test_each_image_plugin_declares_capabilities_that_match_its_fields(kind):
    plugin = get_plugin(kind)
    assert plugin.image is not None and plugin.image.check(plugin) == []


def roles_of(catalog, model_id):
    description = describe_runtime(model_id, catalog.runtimes[model_id], [])
    return description["generation"]["image"]["roles"]


def test_the_form_and_roles_narrow_to_what_each_model_takes():
    # Z-Image Turbo is distilled: no negative prompt, and on the Mac no Quality field (the preset decides).
    z = {"prompt": "prompt", "shape": "size", "width": "width", "height": "height", "start": "picture", "strength": "strength", "steps": "steps", "seed": "seed"}
    assert roles_of(MAC, "z_image") == {"": z}
    assert roles_of(MAC, "qwen_image_2512")[""]["negative"] == "negative_prompt" and "quality" not in roles_of(MAC, "qwen_image_2512")[""]
    assert roles_of(MAC, "qwen_image")[""]["negative"] == "negative_prompt"  # its full preset uses one
    plugin = get_plugin("qwen_image")
    keys = lambda model_id: set(plugin.mode_inputs(None, MAC.runtimes[model_id]))
    assert keys("z_image") == {"prompt", "size", "width", "height", "picture", "strength", "steps", "seed"} and "quality" not in keys("qwen_image")
    # The Windows model keeps its Quality field.
    windows = plugin.mode_inputs(None, WINDOWS.runtimes["qwen_image"])
    assert "quality" in windows and not {"width", "height", "picture", "strength", "steps"} & set(windows)
    assert windows["size"].options == ("square", "portrait", "landscape", "wide")  # the Windows worker has only the four shapes
    assert "custom" in plugin.mode_inputs(None, MAC.runtimes["z_image"])["size"].options
    # A request for a field the model does not have is refused, as for any unknown field.
    with pytest.raises(Exception, match="quality"):
        validate_inputs(plugin, {"prompt": "a fox", "quality": "best"}, None, MAC.runtimes["z_image"])
    assert validate_inputs(plugin, {"prompt": "a fox", "size": "wide"}, None, MAC.runtimes["z_image"])["size"] == "wide"


def test_only_h3_edits_pictures_and_its_picture_tabs_are_the_image_ones():
    h3 = get_plugin("minimax_h3").image
    assert h3.create == "picture" and h3.edit == "edit" and set(h3.roles) == {"picture", "edit"}
    assert get_plugin("qwen_image").image.edit is None


def test_a_custom_size_and_a_starting_picture_are_checked_on_the_mac_models(tmp_path):
    from generationstation.uploads import UploadStore
    plugin, runtime = get_plugin("qwen_image"), MAC.runtimes["z_image"]
    uploads = UploadStore(tmp_path)
    picture = uploads.save("start.png", [b"\x89PNG\r\n\x1a\n" + b"0" * 20])
    values = validate_inputs(plugin, {"prompt": "a fox", "size": "custom", "width": 1280, "height": 720, "picture": [picture["id"]], "strength": 30, "steps": 6}, uploads.get, runtime)
    assert (values["width"], values["height"], values["strength"], values["steps"]) == (1280, 720, 30, 6)
    with pytest.raises(Exception, match="starting picture"):
        validate_inputs(plugin, {"prompt": "a fox", "size": "match picture"}, uploads.get, runtime)
    assert validate_inputs(plugin, {"prompt": "a fox", "size": "match picture", "picture": [picture["id"]]}, uploads.get, runtime)["size"] == "match picture"
    with pytest.raises(Exception, match="(?i)width"):
        validate_inputs(plugin, {"prompt": "a fox", "size": "custom", "width": 100, "height": 720}, uploads.get, runtime)
