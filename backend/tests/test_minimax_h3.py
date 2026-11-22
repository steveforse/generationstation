"""MiniMax H3 plugin: catalog entry, form, launch config, and the worker's prompt building (no model is loaded)."""
import json
import sys
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.plugins.worker import WORKERS_DIR
from generationstation.runtimes import SettingsError, parse_catalog, resolve_settings, validate_inputs

H3 = get_plugin("minimax_h3")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def worker():
    sys.path.insert(0, str(WORKERS_DIR))
    try:
        import minimax_h3_worker
        yield minimax_h3_worker
    finally:
        sys.path.remove(str(WORKERS_DIR))


def test_form_defaults_and_refusals():
    values = validate_inputs(H3, {"prompt": "  a fox in the snow  "})
    assert values == {"mode": "text", "prompt": "a fox in the snow", "shape": "landscape 16:9", "resolution": "540p",
                      "quality": "turbo", "style": "none"}
    for inputs, message in [
        ({"sounds": "wind"}, "Description is required"),
        ({"prompt": "x", "length": "10"}, "not an input"),
        ({"prompt": "x", "shape": "1920x1080"}, "must be one of"),
        ({"prompt": "x" * 3001}, "too long"),
        ({"prompt": "x", "text_encoder_dir": "C:/evil"}, "not an input"),
        ({"prompt": "x", "mode": "dream"}, "mode must be one of"),
        ({"prompt": "x", "first": ["0" * 32]}, "not an input"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(H3, inputs)


def test_example_entry_is_valid_and_only_the_5090_is_allowed(tmp_path):
    catalog = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text()))
    runtime = catalog.runtimes["minimax_h3"]
    preset = runtime.presets["uncensored"]
    assert preset.allowed_gpus == [0] and preset.options["transformer"].endswith("nvfp4.safetensors")
    with pytest.raises(SettingsError):
        resolve_settings(H3, preset, {}, [1])
    values, gpus = resolve_settings(H3, preset, {"compile": False}, [0])
    assert H3.estimate(runtime, preset, values, gpus) == (preset.estimate.ram_gib, {0: preset.estimate.gpu_min_free_gib[0]})
    spec = H3.launch(runtime, preset, values, gpus, {"PATH": "C:/Windows"}, tmp_path)
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "0"
    config = json.loads(spec.files["worker-config.json"])
    assert config["settings"] == {"compile": False} and config["options"]["turbo_lora"].endswith(".safetensors")
    assert H3.script_path(runtime).name == "minimax_h3_worker.py" and H3.script_path(runtime).is_file()


def test_prompt_is_wrapped_in_h3_structure(worker):
    prompt = worker.build_prompt({"prompt": 'A woman on a rainy platform says: "Wait for me by the clock." A train passes.',
                                  "sounds": "Rain on a metal roof", "style": "handheld"})
    assert worker.build_prompt({"prompt": "A fox"}) == worker.build_prompt({"prompt": "A fox", "style": "as written"})
    assert prompt == (
        "integrated_multimodal_description: [Shot 1] Live-action, handheld, A woman on a rainy platform "
        "(S1) says: <d>[English] Wait for me by the clock.</d> A train passes.\n\n"
        "overall_soundscape: Rain on a metal roof\n\nnon_diegetic_music: None.")
    plain = worker.build_prompt({"prompt": "A fox", "music": "Soft guitar", "style": "none"})
    assert plain.startswith("integrated_multimodal_description: [Shot 1] A fox\n\n")
    assert "Natural sounds" in plain and plain.endswith("non_diegetic_music: Soft guitar")


def test_pictures_get_minimax_alignment_line(worker):
    body = {"prompt": "She turns.", "style": "none"}
    start = worker.build_prompt(body, first=True, seconds=124 / 24)
    assert start.startswith("For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) "
                            "is fully referenced.\n\nintegrated_multimodal_description: [Shot 1] She turns.")
    both = worker.build_prompt(body, first=True, last=True, seconds=124 / 24)
    assert both.startswith("How the reference pictures align with the target video \u2014 Picture 1 (from Shot 1) aligns "
                           "with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the "
                           "5.17-second mark of the target video.\n\n")
    end = worker.build_prompt(body, last=True, seconds=124 / 24)
    assert end.startswith("How the reference pictures align with the target video \u2014 <Picture 1> (from [Shot 1]) "
                          "aligns with the 5.17-second mark of the target video.\n\n")
    raw = "integrated_multimodal_description: [Shot 1] x\n\noverall_soundscape: y\n\nnon_diegetic_music: None."
    assert worker.build_prompt({"prompt": raw}, first=True).endswith("\n\n" + raw)
    assert worker.build_prompt({"prompt": both}, first=True, last=True) == both


class Picture:  # just enough of a PIL image: a size and crop
    def __init__(self, width, height):
        self.width, self.height = width, height

    def crop(self, box):
        left, top, right, bottom = box
        return Picture(right - left, bottom - top)


def test_sizes_follow_shape_and_resolution(worker):
    size = worker.canvas_size
    assert size({}) == (960, 544)
    assert size({"shape": "portrait 9:16", "resolution": "720p"}) == (704, 1248)
    assert size({"shape": "square 1:1", "resolution": "240p"}) == (256, 256)
    assert size({"shape": "portrait 4:5", "resolution": "480p"}) == (480, 608)
    assert size({"shape": "classic 4:3", "resolution": "360p"}) == (480, 352)
    assert size({"shape": "landscape", "resolution": "540p"}) == (960, 544)  # older jobs' shape names
    assert size({"shape": "match picture", "resolution": "540p"}, Picture(1000, 1000)) == (544, 544)
    assert size({"shape": "match picture", "resolution": "720p"}, Picture(1080, 1920)) == (704, 1248)
    assert size({"resolution": "custom", "width": 1000, "height": 700}) == (992, 704)
    for inputs in ({"shape": "landscape 16:9", "resolution": "720p"}, {"resolution": "custom", "width": 1344, "height": 1344},
                   {"shape": "match picture", "resolution": "720p"}):
        w, h = size(inputs, Picture(4000, 1000))
        assert w % 32 == 0 and h % 32 == 0 and w * h <= 1280 * 720


def test_framing_crops_the_chosen_part(worker):
    framed = worker._frame_crop(Picture(2000, 1000), "0.5,0,0.25,1", 544, 960)
    assert (framed.width, framed.height) == (500, 882)  # the chosen strip, then exact 544:960
    centred = worker._frame_crop(Picture(2000, 1000), None, 544, 544)
    assert (centred.width, centred.height) == (1000, 1000)


def test_a_full_h3_prompt_is_used_as_written(worker):
    raw = "integrated_multimodal_description: [Shot 1] x\noverall_soundscape: y\nnon_diegetic_music: None."
    assert worker.build_prompt({"prompt": raw, "sounds": "ignored"}) == raw


def test_worker_frame_counts_and_shapes_suit_h3(worker):
    assert all((frames - 5) % 17 == 0 for frames in worker.LENGTHS.values())
    assert set(worker.SHORT_EDGE) | {"custom"} == set(H3.modes["text"].inputs["resolution"].options)
    assert all(edge % 32 == 0 for edge in worker.SHORT_EDGE.values())
    assert set(worker.STYLES) == set(H3.modes["text"].inputs["style"].options)


def test_pictures_mode_takes_one_picture_per_end_and_needs_at_least_one():
    uploads = {"a" * 32: {"kind": "image", "name": "start.png"}, "b" * 32: {"kind": "image", "name": "end.jpg"},
               "c" * 32: {"kind": "audio", "name": "voice.wav"}}
    look = uploads.get
    values = validate_inputs(H3, {"mode": "frames", "prompt": "she turns", "first": ["a" * 32]}, look)
    assert values["mode"] == "frames" and values["first"] == ["a" * 32] and values["shape"] == "match picture"
    for inputs, message in [
        ({"mode": "frames", "prompt": "x"}, "Add a first frame, a last frame, or both"),
        ({"mode": "frames", "prompt": "x", "first": ["a" * 32, "b" * 32]}, "takes at most 1"),
        ({"mode": "frames", "prompt": "x", "last": ["c" * 32]}, "takes only image files"),
        ({"mode": "frames", "prompt": "x", "last": ["d" * 32]}, "missing or has expired"),
        ({"mode": "frames", "prompt": "x", "last": "b" * 32}, "must be a list"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(H3, inputs, look)


def test_a_job_keeps_its_own_copies_of_the_pictures(tmp_path):
    from generationstation.generation import GenerationManager
    from generationstation.lifecycle import LifecycleError
    from generationstation.uploads import UploadStore

    data = json.loads((ROOT / "runtimes.example.json").read_text())
    data["runtimes"]["minimax_h3"]["output_dir"] = str(tmp_path / "out")
    catalog = parse_catalog(data)
    uploads = UploadStore(tmp_path / "runtime")
    picture = uploads.save("first.png", [b"\x89PNG\r\n\x1a\n" + b"\x00" * 8])

    class Store:
        def __init__(self):
            self.jobs = {}

        def get_job(self, job_id):
            return self.jobs.get(job_id)

    store = Store()
    manager = GenerationManager(store, catalog, uploads)
    values = validate_inputs(H3, {"mode": "frames", "prompt": "x", "first": [picture["id"]]}, uploads.get)
    stored, worker = manager._attach_files(H3, catalog.runtimes["minimax_h3"], "job-1", values)
    assert stored["first"] == [{"name": "01-first.png", "kind": "image", "mime": "image/png", "original": "first.png"}]
    path = tmp_path / "out" / "job-1" / "inputs" / "01-first.png"
    assert worker["first"][0]["path"] == str(path) and path.is_file()
    store.jobs["job-1"] = {"id": "job-1", "model_id": "minimax_h3", "inputs": stored}
    assert manager.input_path("job-1", "01-first.png") == (path.resolve(), "image/png")
    for bad in ("../job.json", "02-other.png"):
        with pytest.raises(LifecycleError):
            manager.input_path("job-1", bad)


def test_reference_prompt_follows_minimax_sections_and_labels(worker):
    prompt = worker.build_reference_prompt({
        "prompt": 'The woman from picture 1 walks to the lighthouse in Picture 2 and says: "I came back." The camera moves like video 1.',
        "notes": "Picture 1: a young woman in a green coat\npicture 2 - a white lighthouse", "video_use": "copy camera and motion",
        "audio_use": "voice to imitate", "style": "cinematic"}, pictures=2, videos=1, audios=1)
    sections = [part.split(":\n", 1)[0] for part in prompt.split("\n\n")]
    assert sections == ["subject_definitions", "summary", "retention_analysis", "detailed_description",
                        "overall_soundscape", "non_diegetic_music"]
    assert "<Subject 1> is a young woman in a green coat in <Picture 1>, as it appears there." in prompt
    assert "<Subject 2> is a white lighthouse in <Picture 2>" in prompt
    assert "<Video 1> is the camera-movement and pacing reference" in prompt
    assert "<Audio 1> is the voice-timbre reference for the speaker (S1)." in prompt
    assert "summary:\n[reference generation + audio reference] The woman from <Subject 1> walks" in prompt
    assert ("[Shot 1] The woman from <Subject 1> walks to the lighthouse in <Subject 2> and (S1) says: "
            "<d>[English] I came back.</d> The camera moves like <Video 1>.") in prompt
    assert "The target video uses a live-action, cinematic style.\n[Shot 1]" in prompt
    assert prompt.endswith("non_diegetic_music:\nN/A")


def test_reference_prompt_for_edits_soundtracks_and_written_prompts(worker):
    edit = worker.build_reference_prompt({"prompt": "Make it snow in video 1.", "video_use": "edit them",
                                          "audio_use": "soundtrack to keep"}, pictures=0, videos=1, audios=1)
    assert "summary:\n[video editing + audio reuse] The target video is an edited version of <Video 1>. Make it snow in <Video 1>." in edit
    assert "<Audio 1> plays as the complete soundtrack." in edit
    written = "subject_definitions:\n<Subject 1> is x in <Picture 1>.\n\nsummary:\n..."
    assert worker.build_reference_prompt({"prompt": written}, 1, 0, 0) == written


def test_reference_mode_limits():
    uploads = {f"{i:032x}": {"kind": kind, "name": "x"} for i, kind in enumerate(["image"] * 10 + ["video"] * 3 + ["audio"] * 3)}
    ids = {kind: [key for key, value in uploads.items() if value["kind"] == kind] for kind in ("image", "video", "audio")}
    ok = validate_inputs(H3, {"mode": "reference", "prompt": "x", "images": ids["image"][:9], "audio": ids["audio"][:3]}, uploads.get)
    assert ok["quality"] == "standard" and len(ok["images"]) == 9
    for inputs, message in [
        ({"audio": ids["audio"][:1]}, "Add at least one picture or video"),
        ({"images": ids["image"][:10]}, "takes at most 9"),
        ({"images": ids["image"][:9], "videos": ids["video"][:2], "audio": ids["audio"][:2]}, "at most 12 references"),
        ({"images": ids["image"][:1], "quality": "turbo"}, "must be one of extreme, high, standard"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(H3, {"mode": "reference", "prompt": "x", **inputs}, uploads.get)


def test_pictures_are_cropped_not_stretched_to_another_shape(worker):
    wide = worker._cover(Picture(1000, 1000), 960, 544)
    assert (wide.width, wide.height) == (1000, 567)
    tall = worker._cover(Picture(1920, 1080), 544, 960)
    assert (tall.width, tall.height) == (612, 1080)
    square = Picture(1000, 1000)
    assert worker._cover(square, 736, 736) is square and worker._cover(None, 1, 1) is None


def test_framing_and_custom_size_are_checked():
    uploads = {"a" * 32: {"kind": "image", "name": "start.png"}}
    ok = validate_inputs(H3, {"mode": "frames", "prompt": "x", "first": ["a" * 32], "shape": "portrait 9:16",
                              "first_crop": "0.25,0,0.5,1"}, uploads.get)
    assert ok["first_crop"] == "0.25,0,0.5,1"
    for inputs, message in [
        ({"first_crop": "0.8,0,0.5,1"}, "four fractions"),
        ({"first_crop": "a,b,c,d"}, "four fractions"),
        ({"resolution": "custom", "width": 1344, "height": 1344}, "too large"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(H3, {"mode": "frames", "prompt": "x", "first": ["a" * 32], **inputs}, uploads.get)


def test_quality_levels_map_to_steps_and_old_names_still_work(worker):
    assert worker.STEPS == {"turbo": 4, "standard": 20, "high": 30, "extreme": 50}
    assert set(worker.STEPS) == set(H3.modes["text"].inputs["quality"].options)
    assert set(H3.modes["reference"].inputs["quality"].options) == {"standard", "high", "extreme"}
    assert worker.QUALITY_ALIASES == {"quick": "turbo", "best": "standard"}


def test_custom_size_shows_only_for_custom_and_choices_run_high_to_low():
    fields = H3.modes["text"].inputs
    assert fields["width"].show_when == {"resolution": "custom"} and not fields["width"].advanced
    assert list(fields)[list(fields).index("resolution") + 1:][:2] == ["width", "height"]
    assert fields["resolution"].options[:6] == ("1080p (upscaled)", "720p", "540p", "480p", "360p", "240p")
    assert fields["quality"].options == ("extreme", "high", "standard", "turbo") and fields["quality"].default == "turbo"


def test_1080p_renders_at_720p_then_resizes_to_exact_proportions(worker):
    inputs = {"resolution": "1080p (upscaled)", "shape": "landscape 16:9"}
    assert worker.canvas_size(inputs) == (1248, 704)
    assert worker.output_size(inputs) == (1920, 1080)
    assert worker.output_size({**inputs, "shape": "portrait 9:16"}) == (1080, 1920)
    assert worker.output_size({**inputs, "shape": "portrait 4:5"}) == (1080, 1350)
    assert worker.output_size({**inputs, "shape": "match picture"}, Picture(1000, 1000)) == (1080, 1080)
    assert worker.output_size({"resolution": "720p"}) is None


def test_look_defaults_to_none_in_every_tab():
    for mode in H3.modes.values():
        assert mode.inputs["style"].default == "none" and mode.inputs["style"].options[0] == "none"


def test_turbo_reads_low_fast():
    quality = H3.modes["text"].inputs["quality"]
    assert quality.option_labels == {"turbo": "Low (Fast)"} and quality.help.startswith("Low (Fast): 4 steps")


def test_custom_size_is_kept_only_with_resolution_custom():
    plain = validate_inputs(H3, {"prompt": "x", "width": 640, "height": 360})
    assert "width" not in plain and "height" not in plain
    custom = validate_inputs(H3, {"prompt": "x", "resolution": "custom", "width": 640, "height": 360})
    assert (custom["width"], custom["height"]) == (640, 360)
    assert validate_inputs(H3, {"prompt": "x", "resolution": "custom"})["width"] == 960  # the starting size
