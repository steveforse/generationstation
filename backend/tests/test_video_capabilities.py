"""The video models' declared capabilities must agree with their own tabs and fields, and narrow per model."""
import json
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import describe_runtime, parse_catalog, validate_inputs
from generationstation.uploads import UploadStore

ROOT = Path(__file__).resolve().parents[2]
MAC = parse_catalog(json.loads((ROOT / "runtimes.mac.example.json").read_text()))
WINDOWS = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text()))
KINDS = ["wan_video", "fastmetal_video", "longcat_video", "ltx_video", "h3_video", "minimax_h3"]


@pytest.mark.parametrize("kind", KINDS)
def test_each_video_plugin_declares_capabilities_that_match_its_fields(kind):
    plugin = get_plugin(kind)
    assert plugin.video is not None and plugin.video.check(plugin) == []


def video_of(catalog, model_id):
    return describe_runtime(model_id, catalog.runtimes[model_id], [])["generation"]["video"]


def test_the_roles_say_what_each_model_takes():
    assert set(video_of(MAC, "fastmetal_video")["roles"][""]) == {"prompt", "shape", "length", "speed", "seed"}
    longcat = video_of(MAC, "longcat_video")
    assert set(longcat["roles"]) == {"text", "image", "continue"} and longcat["extend"] == "continue" and longcat["sound"] == "none"
    ltx = video_of(MAC, "ltx_video")
    assert {"first", "last"} <= set(ltx["roles"]["image"]) and ltx["sound"] == "automatic" and ltx["extend"] in (None, "")
    assert "first" in video_of(MAC, "wan_video")["roles"]["image"]


def test_every_length_option_has_seconds_so_a_length_carries_across_models():
    for kind in KINDS:
        plugin = get_plugin(kind)
        for mode, roles in plugin.video.roles.items():
            field = roles.get("length")
            if field:
                inputs = plugin.modes[mode].inputs if plugin.modes else plugin.inputs
                assert set(inputs[field].options) <= set(plugin.video.seconds), (kind, mode)


def test_longcat_tabs_need_their_picture_or_clip_and_the_old_form_still_works(tmp_path):
    plugin, runtime = get_plugin("longcat_video"), MAC.runtimes["longcat_video"]
    uploads = UploadStore(tmp_path)
    clip = uploads.save("clip.mp4", [b"\x00\x00\x00\x18ftypmp42" + b"0" * 20])
    old = validate_inputs(plugin, {"prompt": "a fox", "length": "short"}, uploads.get, runtime)  # no mode: a result from before the tabs
    assert old["length"] == "short"
    cont = validate_inputs(plugin, {"mode": "continue", "prompt": "it runs on", "source": [clip["id"]]}, uploads.get, runtime)
    assert cont["source"]
    with pytest.raises(Exception, match="required"):
        validate_inputs(plugin, {"mode": "continue", "prompt": "it runs on"}, uploads.get, runtime)
    with pytest.raises(Exception, match="required"):
        validate_inputs(plugin, {"mode": "image", "prompt": "it moves"}, uploads.get, runtime)
