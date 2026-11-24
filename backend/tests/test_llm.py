"""Text models: one entry per model; the card chosen decides which engine runs it, and nothing else shows that."""
import json

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, describe_runtime, parse_catalog, resolve_settings

LLM = get_plugin("llm")
STRATA = {"engine": "strata", "python": "C:/strata/python/python.exe", "server_dir": "C:/strata",
          "component": "component:strata-inkling", "pack": "D:/ink/SQ-10.strata", "vision_pack": "D:/ink/Vision.strata",
          "tokenizer": "D:/ink/tokenizer", "arch": "inkling2_loop", "model_name": "inkling-2-mini", "drafter": "dspark",
          "sampling": {"temperature": 1.0, "top_k": 50}, "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"1": 12.5}}}
BASALT = {"engine": "basalt", "executable": "C:/basalt/bin/basalt.exe", "working_dir": "C:/basalt",
          "path_prepend": ["C:/cuda"], "alias": "Inkling-Unbound", "model_path": "D:/unbound.basalt",
          "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"0": 24}}}


def catalog():
    return parse_catalog({"runtimes": {"inkling2": {
        "kind": "llm", "name": "Inkling 2 Mini", "workload": "text", "port": 8161, "default_preset": "main",
        "presets": {"main": {
            "name": "Inkling 2 Mini", "gpus": [1], "allowed_gpus": [0, 1], "kv_options": ["fp8", "fp16"],
            "settings": {"max_context": 131072, "vision": "card", "kv": "fp8", "vram_reserve_mib": 700},
            "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"0": 24, "1": 12.5}},
            "card_notes": {"1": "The standard model.", "0": "Does not refuse requests."},
            "cards": {"1": STRATA, "0": BASALT}}}}}})


def setup():
    runtime = catalog().runtimes["inkling2"]
    return runtime, runtime.presets["main"]


def test_one_card_at_a_time_and_only_cards_with_a_setup():
    _, preset = setup()
    assert LLM.gpu_limit(preset) == 1
    with pytest.raises(SettingsError, match="1 GPU at a time"):
        resolve_settings(LLM, preset, {}, [0, 1])
    values, gpus = resolve_settings(LLM, preset, {}, [0])
    assert gpus == [0] and values["vision"] == "card"


def test_the_4080_runs_strata_with_the_settings_as_engine_flags(tmp_path):
    runtime, preset = setup()
    values, gpus = resolve_settings(LLM, preset, {"max_context": 65536}, [1])
    spec = LLM.launch(runtime, preset, values, gpus, {"PATH": "P"}, tmp_path)
    assert spec.argv[0] == "C:/strata/python/python.exe" and spec.argv[2:4] == ["--engine", "strata"]
    assert spec.argv[1].replace("\\", "/") == "C:/strata/serve/server.py"
    assert spec.argv[spec.argv.index("--gpu") + 1] == "1" and spec.argv[spec.argv.index("--port") + 1] == "8161"
    assert "--no-api-key" in spec.argv and spec.cwd == "C:/strata"
    config = json.loads(spec.files["strata-config.json"])
    assert config["exe"] == "component:strata-inkling" and config["gpu"] == 1 and config["parallel"] == 1
    args = config["args"]
    assert args[:2] == ["--native", "D:/ink/SQ-10.strata"]
    for flag, value in [("--max-context", "65536"), ("--vision", "D:/ink/Vision.strata"), ("--kv", "fp8"),
                        ("--vram-reserve-mib", "700"), ("--draft", "dspark")]:
        assert args[args.index(flag) + 1] == value
    values_off, _ = resolve_settings(LLM, preset, {"vision": "off"}, [1])
    assert "--vision" not in json.loads(LLM.launch(runtime, preset, values_off, [1], {}, tmp_path).files["strata-config.json"])["args"]


def test_the_5090_runs_basalt_with_its_own_keys(tmp_path):
    runtime, preset = setup()
    values, gpus = resolve_settings(LLM, preset, {}, [0])
    spec = LLM.launch(runtime, preset, values, gpus, {"PATH": "P"}, tmp_path)
    assert spec.argv[:2] == ["C:/basalt/bin/basalt.exe", "serve"] and spec.cwd == "C:/basalt"
    assert spec.env["PATH"] == "C:/cuda;P" and spec.env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    entry = json.loads(spec.files["basalt-config.json"])["models"][0]
    assert entry == {"alias": "Inkling-Unbound", "model": "D:/unbound.basalt", "gpu": "0", "max-context": 131072,
                     "vision": "dynamic", "kv": "fp8", "vram-reserve-mib": 700}


def test_estimates_and_chat_sampling_follow_the_card():
    runtime, preset = setup()
    assert LLM.estimate(runtime, preset, {"vision": "card"}, [1]) == (7, {1: 12.5})
    assert LLM.estimate(runtime, preset, {"vision": "off"}, [0]) == (6, {0: 24})
    assert LLM.chat_sampling(preset, [1]) == {"temperature": 1.0, "top_k": 50}
    assert LLM.chat_sampling(preset, [0]) == {}


def test_the_browser_sees_the_model_not_the_engine():
    entry = describe_runtime("inkling2", catalog().runtimes["inkling2"], [{"index": 0, "name": "RTX 5090"}, {"index": 1, "name": "RTX 4080"}])
    preset = entry["presets"]["main"]
    assert entry["chat"] is True and preset["max_gpus"] == 1
    assert preset["card_notes"] == {"1": "The standard model.", "0": "Does not refuse requests."}
    advanced = {s["key"]: s["advanced"] for s in preset["settings"]}
    assert advanced == {"max_context": True, "vision": False, "kv": True, "vram_reserve_mib": True}
    text = json.dumps(entry).lower()
    assert "strata" not in text and "basalt" not in text


def test_a_card_setup_must_name_its_files():
    broken = dict(STRATA); broken.pop("pack")
    with pytest.raises(Exception, match="pack"):
        parse_catalog({"runtimes": {"x": {
            "kind": "llm", "name": "X", "workload": "text", "port": 8165, "default_preset": "main",
            "presets": {"main": {"name": "X", "gpus": [1], "estimate": {"ram_gib": 1, "gpu_min_free_gib": {"1": 1}},
                                 "cards": {"1": broken}}}}}})


def test_inkling_on_strata_can_run_through_the_thinking_wrapper(tmp_path):
    card = dict(STRATA, inkling_thinking=True, thinking_levels=["low", "high"], thinking_default="low")
    runtime = parse_catalog({"runtimes": {"ink": {
        "kind": "llm", "name": "Inkling", "workload": "text", "port": 8161, "default_preset": "main",
        "presets": {"main": {"name": "Inkling", "gpus": [1], "settings": {}, "cards": {"1": card},
                             "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"1": 12.5}}}}}}}).runtimes["ink"]
    preset = runtime.presets["main"]
    spec = LLM.launch(runtime, preset, {}, [1], {}, tmp_path)
    assert spec.argv[1].replace("\\", "/").endswith("workers/strata_inkling_thinking.py")
    assert spec.argv[2] == "C:/strata" and spec.argv[3:5] == ["--engine", "strata"]
    assert LLM.chat_thinking(preset, [1]) == {"levels": ["low", "high"], "default": "low", "off": True}


def test_thinking_levels_are_checked_and_a_card_without_them_offers_none():
    _, preset = setup()
    assert LLM.chat_thinking(preset, [0]) == {"levels": [], "default": None, "off": False}
    for bad in ({"thinking_levels": ["low", "low"]}, {"thinking_levels": ["off", "low"]},
                {"thinking_levels": ["low"], "thinking_default": "high"}):
        with pytest.raises(Exception, match="thinking"):
            parse_catalog({"runtimes": {"x": {
                "kind": "llm", "name": "X", "workload": "text", "port": 8165, "default_preset": "main",
                "presets": {"main": {"name": "X", "gpus": [0], "settings": {}, "cards": {"0": dict(BASALT, **bad)},
                                     "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"0": 24}}}}}}})
