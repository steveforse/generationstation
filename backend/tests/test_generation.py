"""YuE2 plugin and the generation path, using a stand-in worker (no model is loaded)."""
import json
import sys
from pathlib import Path

import pytest

from generationstation.plugins import get_plugin
from generationstation.process_worker import ProcessSupervisor
from generationstation.runtimes import SettingsError, parse_catalog, resolve_settings, validate_inputs
from tests.runtime_fixtures import free_port

YUE2 = get_plugin("yue2")
STUB = str(Path(__file__).with_name("stub_worker.py"))


def yue2_catalog(port, output_dir, *, options=None, script=STUB):
    return parse_catalog({"runtimes": {"yue2": {
        "kind": "yue2", "name": "YuE2 songs", "workload": "music", "port": port,
        "python": sys.executable, "output_dir": str(output_dir), "worker_script": script,
        "ready_timeout_seconds": 20, "stop_timeout_seconds": 10, "default_preset": "songs",
        "presets": {"songs": {
            "name": "YuE2 3B", "gpus": [1], "allowed_gpus": [0, 1],
            "options": {"model_dir": "C:/ai/models/yue2/YuE2-3B", "vae_dir": "C:/ai/models/yue2/YuE2-Vae",
                        **(options or {})},
            "settings": {"memory_budget_gib": 16, "quantization": "none"},
            "estimate": {"ram_gib": 24, "gpu_min_free_gib": {"0": 14, "1": 14}},
        }},
    }}})


def test_inputs_are_validated_against_the_form():
    values = validate_inputs(YUE2, {"style": "  dream pop  ", "lyrics": "[Verse]\nhello", "seed": 7})
    assert values == {"style": "dream pop", "lyrics": "[Verse]\nhello", "mode": "full", "seed": 7}
    for inputs, message in [
        ({"lyrics": "x"}, "Style is required"),
        ({"style": "a", "lyrics": "x" * 9000}, "too long"),
        ({"style": "a", "lyrics": "x", "mode": "turbo"}, "must be one of"),
        ({"style": "a", "lyrics": "x", "seed": "7"}, "whole number"),
        ({"style": "a", "lyrics": "x", "model_dir": "C:/evil"}, "not an input"),
    ]:
        with pytest.raises(SettingsError, match=message):
            validate_inputs(YUE2, inputs)


def test_yue2_runs_on_one_gpu_and_sees_only_that_card(tmp_path):
    runtime = yue2_catalog(8170, tmp_path).runtimes["yue2"]
    preset = runtime.presets["songs"]
    with pytest.raises(SettingsError, match="1 GPU at a time"):
        resolve_settings(YUE2, preset, {}, [0, 1])
    values, gpus = resolve_settings(YUE2, preset, {"quantization": "fp8"}, [1])
    spec = YUE2.launch(runtime, preset, values, gpus, {"PATH": "C:/Windows"}, tmp_path)
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "1" and spec.env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    config = json.loads(spec.files["worker-config.json"])
    assert config["settings"] == {"memory_budget_gib": 16, "quantization": "fp8"}
    assert config["options"]["vae_dir"].endswith("YuE2-Vae") and config["port"] == 8170
    assert spec.argv[0] == sys.executable and spec.argv[1] == STUB
    default = YUE2.script_path(runtime.model_copy(update={"worker_script": None}))
    assert default.name == "yue2_worker.py" and default.is_file()


def wait(predicate, timeout=20):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timed out")


def test_worker_protocol_end_to_end(tmp_path):
    port = free_port()
    runtime = yue2_catalog(port, tmp_path / "out").runtimes["yue2"]
    preset = runtime.presets["songs"]
    values, gpus = resolve_settings(YUE2, preset, {}, None)
    supervisor = ProcessSupervisor(tmp_path / "runtime", poll_seconds=0.1)
    handle = supervisor.spawn("op-1", runtime, preset, values, gpus)
    try:
        assert supervisor.wait_ready(handle, runtime, 20)
        job = YUE2.submit(runtime, "job-00000001", {"style": "pop", "lyrics": "[Verse]\nla", "seed": 3})
        assert job["status"] in {"queued", "running"}
        done = wait(lambda: (r := YUE2.job_status(runtime, "job-00000001")) and r["status"] in {"done", "failed"} and r)
        assert done["status"] == "done", done
        assert done["outputs"] == [{"name": "song.wav", "mime": "audio/wav", "bytes": (tmp_path / "out" / "job-00000001" / "song.wav").stat().st_size}]
        assert done["progress"] == "Done: seed 3"
        YUE2.submit(runtime, "job-00000002", {"style": "fail", "lyrics": "x"})
        failed = wait(lambda: (r := YUE2.job_status(runtime, "job-00000002")) and r["status"] in {"done", "failed"} and r)
        assert failed["status"] == "failed" and "could not be planned" in failed["error"]
        assert YUE2.job_status(runtime, "job-missing1") is None
    finally:
        supervisor.stop(handle)
        supervisor.wait_exited(handle, 10)


def test_a_failed_load_is_reported(tmp_path):
    from generationstation.process_worker import WorkerFailed
    port = free_port()
    runtime = yue2_catalog(port, tmp_path, options={"fail_load": True}).runtimes["yue2"]
    preset = runtime.presets["songs"]
    values, gpus = resolve_settings(YUE2, preset, {}, None)
    supervisor = ProcessSupervisor(tmp_path / "runtime", poll_seconds=0.1)
    handle = supervisor.spawn("op-2", runtime, preset, values, gpus)
    try:
        with pytest.raises(WorkerFailed, match="weights not found") as failure:
            supervisor.wait_ready(handle, runtime, 20)
        assert failure.value.code == "WORKER_FAILED"
    finally:
        supervisor.stop(handle)
        supervisor.wait_exited(handle, 10)
