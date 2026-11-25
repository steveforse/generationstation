"""Text models: one entry per model; the card chosen decides which engine runs it, and nothing else shows that."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.runtimes import SettingsError, describe_runtime, parse_catalog, resolve_settings
from tests.runtime_fixtures import free_port

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


ROOT = Path(__file__).resolve().parents[2]
VLLM = {"engine": "vllm", "executable": "C:/vllm/vllm.exe", "working_dir": "C:/vllm",
        "model_path": "D:/ernie", "fixed_args": ["--trust-remote-code", "--reasoning-parser", "ernie5",
                                                 "--tool-call-parser", "ernie5", "--enable-auto-tool-choice"],
        "estimate": {"ram_gib": 16, "gpu_min_free_gib": {"0": 160, "1": 160}},
        "sampling": {"temperature": 1.0, "top_p": 0.95}}


def vllm_catalog(port):
    return parse_catalog({"runtimes": {"ernie55": {
        "kind": "llm", "name": "ERNIE 5.5", "workload": "text", "port": port, "default_preset": "preview",
        "presets": {"preview": {
            "name": "ERNIE 5.5 Preview", "gpus": [0, 1], "allowed_gpus": [0, 1],
            "kv_options": ["fp8", "auto"], "vision_options": ["off"],
            "settings": {"max_context": 131072, "kv": "fp8", "vision": "off"},
            "estimate": {"ram_gib": 16, "gpu_min_free_gib": {"0": 160, "1": 160}},
            "cards": {"0,1": VLLM}}}}}})


def test_the_example_ernie55_entry_runs_on_vllm_and_refuses_this_desktop(tmp_path):
    runtime = parse_catalog(json.loads((ROOT / "runtimes.example.json").read_text())).runtimes["ernie55"]
    preset = runtime.presets["preview"]
    assert runtime.port == 8163 and preset.cards["0,1"].engine == "vllm"
    values, gpus = resolve_settings(LLM, preset, {}, [0, 1])
    assert LLM.estimate(runtime, preset, values, gpus) == (16, {0: 160, 1: 160})
    assert LLM.chat_sampling(preset, gpus) == {"temperature": 1.0, "top_p": 0.95}
    assert LLM.chat_thinking(preset, gpus, False) == {"chat_template_kwargs": {"enable_thinking": False}}
    assert LLM.chat_thinking(preset, gpus, True) == {"chat_template_kwargs": {"enable_thinking": True}}
    spec = LLM.launch(runtime, preset, values, gpus, {"PATH": "P"}, tmp_path)
    assert spec.argv[:3] == [
        "C:\\ai\\envs\\ernie55\\Scripts\\vllm.exe", "serve",
        "D:\\ai\\models\\ernie-5.5\\ERNIE-5.5-Flash-Preview-FP8",
    ]
    assert spec.argv[spec.argv.index("--data-parallel-size") + 1] == "2"
    assert spec.argv[spec.argv.index("--max-model-len") + 1] == "131072"
    assert spec.argv[spec.argv.index("--kv-cache-dtype") + 1] == "fp8"
    assert "--reasoning-parser" in spec.argv and "--tool-call-parser" in spec.argv
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "0,1"
    assert spec.env["VLLM_ENGINE_READY_TIMEOUT_S"] == "3600"
    assert spec.cwd == "C:\\ai\\envs\\ernie55"


def test_one_vllm_card_setup_needs_both_cards(tmp_path):
    runtime = vllm_catalog(8163).runtimes["ernie55"]
    preset = runtime.presets["preview"]
    with pytest.raises(SettingsError, match="runs on GPU 0,1"):
        resolve_settings(LLM, preset, {}, [0])
    values, gpus = resolve_settings(LLM, preset, {}, [0, 1])
    spec = LLM.launch(runtime, preset, values, gpus, {}, tmp_path)
    assert spec.argv[0] == "C:/vllm/vllm.exe" and spec.argv[1:3] == ["serve", "D:/ernie"]
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "0,1"


def test_vllm_model_list_is_loaded_without_a_status_field():
    port = free_port()
    runtime = vllm_catalog(port).runtimes["ernie55"]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/v1/models":
                body = json.dumps({"object": "list", "data": [{"id": "ERNIE-5.5-Flash-Preview"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert LLM.probe(runtime) == "loaded"
    finally:
        server.shutdown()
        server.server_close()
