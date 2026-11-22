import json
from copy import deepcopy

import pytest

from generationstation.plugins import get_plugin, plugin_kinds
from generationstation.plugins.base import RuntimePlugin
from generationstation.process_worker import ProcessSupervisor, WorkerFailed
from generationstation.runtimes import (
    GIB,
    CatalogError,
    SettingsError,
    describe_runtime,
    estimate_requirements,
    load_catalog,
    parse_catalog,
    resolve_settings,
)
from tests.runtime_fixtures import catalog, catalog_data, free_port, host

BASALT = get_plugin("basalt")


# ----- plugin contract: every registered plugin must satisfy these -------------------------

@pytest.mark.parametrize("kind", plugin_kinds())
def test_plugin_contract(kind):
    plugin = get_plugin(kind)
    assert isinstance(plugin, RuntimePlugin) and plugin.kind == kind and plugin.title
    assert plugin.runtime_model.model_fields["kind"].annotation is not str, "narrow kind to a Literal"
    for name, spec in plugin.settings.items():
        assert name.isidentifier() and spec.label and spec.help and spec.target
        if spec.kind in {"int", "optional_int"}:
            assert spec.minimum is not None and spec.maximum is not None and spec.minimum <= spec.maximum
    for method in ("launch", "probe"):
        assert getattr(type(plugin), method) is not getattr(RuntimePlugin, method), f"{kind} must implement {method}"
    if plugin.generates:
        assert plugin.output_kind in {"audio", "image", "video"}
    for timing in plugin.timings:  # timings may only name modes and form choices that exist
        if plugin.modes and "mode" not in timing.when:  # applies to every tab: check against all of them
            specs = {key: spec for mode in plugin.modes.values() for key, spec in mode.inputs.items()}
        else:
            specs = plugin.mode_inputs(timing.when.get("mode"))
        assert specs is not None, (kind, timing.when)
        for key, value in timing.when.items():
            if key != "mode":
                assert specs[key].kind == "choice" and value in specs[key].options, (kind, key, value)
    for mode in plugin.modes.values():
        assert mode.label and mode.help and mode.inputs
    for spec in [*plugin.inputs.values(), *(s for m in plugin.modes.values() for s in m.inputs.values())]:
        if spec.kind == "files":
            assert spec.accept and spec.max_count
        for method in ("submit", "job_status", "output_dir"):
            assert getattr(type(plugin), method) is not getattr(RuntimePlugin, method), f"{kind} must implement {method}"
        for name, spec in plugin.inputs.items():
            assert name.isidentifier() and spec.label and spec.help
            if spec.kind in {"text", "textarea"}:
                assert spec.max_length, f"{kind}.{name} needs a max_length"
            if spec.kind == "choice":
                assert spec.options and (spec.default is None or spec.default in spec.options)


# ----- catalog ---------------------------------------------------------------------------------

def test_missing_catalog_means_no_runtimes(tmp_path):
    assert load_catalog(tmp_path / "absent.json").runtimes == {}
    assert load_catalog(None).runtimes == {}


def test_broken_catalog_is_an_error(tmp_path):
    path = tmp_path / "runtimes.json"
    path.write_text(json.dumps({"runtimes": {"basalt": {"kind": "basalt"}}}))
    with pytest.raises(CatalogError):
        load_catalog(path)


def test_unknown_plugin_kind_names_the_available_ones():
    data = catalog_data(8160)
    data["runtimes"]["basalt"]["kind"] = "comfy"
    with pytest.raises(CatalogError, match="unknown kind 'comfy'.*basalt"):
        parse_catalog(data)


def test_preset_defaults_must_be_known_settings():
    data = deepcopy(catalog_data(8160))
    data["runtimes"]["basalt"]["presets"]["ds41"]["settings"]["gpu_layers"] = 3
    with pytest.raises(CatalogError, match="unknown settings gpu_layers"):
        parse_catalog(data)
    data = deepcopy(catalog_data(8160))
    data["runtimes"]["basalt"]["presets"]["fn"]["settings"]["kv"] = "fp16"
    with pytest.raises(CatalogError, match="kv must be one of"):
        parse_catalog(data)


# ----- settings --------------------------------------------------------------------------------

def test_overrides_are_validated_against_the_preset():
    preset = catalog(8160).runtimes["basalt"].presets["ds41"]
    values, gpus = resolve_settings(BASALT, preset, {"vram_reserve_mib": 1024, "resident_budget_gib": None}, [1, 0])
    assert values["vram_reserve_mib"] == 1024 and values["resident_budget_gib"] is None
    assert gpus == [0, 1]
    for overrides, message in [
        ({"vram_reserve_mib": 100}, "at least 256"),
        ({"vram_reserve_mib": "700"}, "whole number"),
        ({"kv": "int8"}, "cannot be changed"),        # DeepSeek preset does not expose kv
        ({"model": "C:/evil.basalt"}, "cannot be changed"),
        ({"max_context": 2_000_000}, "at most"),
    ]:
        with pytest.raises(SettingsError, match=message):
            resolve_settings(BASALT, preset, overrides, None)
    with pytest.raises(SettingsError, match="not allowed"):
        resolve_settings(BASALT, preset, {}, [2])
    with pytest.raises(SettingsError, match="at least one GPU"):
        resolve_settings(BASALT, preset, {}, [])


def test_choice_and_bool_settings():
    preset = catalog(8160).runtimes["basalt"].presets["fn"]
    values, _ = resolve_settings(BASALT, preset, {"kv": "q4_0", "resident_experts": False}, None)
    assert values["kv"] == "q4_0" and values["resident_experts"] is False
    with pytest.raises(SettingsError, match="one of"):
        resolve_settings(BASALT, preset, {"kv": "fp16"}, None)
    with pytest.raises(SettingsError, match="on or off"):
        resolve_settings(BASALT, preset, {"resident_experts": 1}, None)


# ----- Basalt plugin ---------------------------------------------------------------------------

def test_basalt_config_matches_its_format():
    runtime = catalog(8160).runtimes["basalt"]
    preset = runtime.presets["fn"]
    values, gpus = resolve_settings(BASALT, preset, {}, [0])
    config = BASALT.config(runtime, preset, values, gpus)
    assert config["version"] == 2 and config["server"] == {"host": "127.0.0.1", "port": 8160}
    entry = config["models"][0]
    assert entry["gpu"] == "0" and entry["model"] == "C:/models/fn.basalt" and entry["ple-io"] == "direct"
    assert entry["vram-reserve-mib"] == 700 and entry["resident-experts"] is True
    assert "resident-budget-gib" not in entry  # automatic


def test_basalt_launch_orders_gpus_like_nvml(tmp_path):
    runtime = catalog(8160).runtimes["basalt"]
    runtime.path_prepend = ["C:/cuda/bin"]
    preset = runtime.presets["ds41"]
    values, gpus = resolve_settings(BASALT, preset, {}, None)
    spec = BASALT.launch(runtime, preset, values, gpus, {"PATH": "C:/Windows"}, tmp_path)
    assert spec.env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert spec.env["PATH"].startswith("C:/cuda/bin;") and spec.env["BASALT_ENGRAM_OFFSET"] == "416"
    assert spec.argv[-3:] == ["serve", "--config", str(tmp_path / "basalt-config.json")]
    assert set(spec.files) == {"basalt-config.json"}


def test_estimate_maps_indices_to_device_ids():
    runtime = catalog(8160).runtimes["basalt"]
    preset = runtime.presets["ds41"]
    values, gpus = resolve_settings(BASALT, preset, {}, None)
    ram, gpu = estimate_requirements(BASALT, runtime, preset, values, gpus, host()["gpus"])
    assert ram == (8 + 48) * GIB
    assert gpu == {"GPU-0": 24 * GIB, "GPU-1": 10 * GIB}
    _, single = estimate_requirements(BASALT, runtime, preset, values, [0], host()["gpus"])
    assert single == {"GPU-0": 24 * GIB}
    with pytest.raises(SettingsError, match="not reported"):
        estimate_requirements(BASALT, runtime, preset, values, gpus, host()["gpus"][:1])


def test_description_hides_paths_and_environment():
    runtime = catalog(8160).runtimes["basalt"]
    text = json.dumps(describe_runtime("basalt", runtime, host()["gpus"]))
    assert "fn.basalt" not in text and "ENGRAM" not in text and "python" not in text.lower()
    described = describe_runtime("basalt", runtime, host()["gpus"])
    assert described["plugin"] == "Basalt"
    assert described["presets"]["ds41"]["allowed_gpus"][1]["name"] == "RTX 4080"
    kv = next(s for s in described["presets"]["fn"]["settings"] if s["key"] == "kv")
    assert kv["options"] == ["int8", "q4_0"]


# ----- process supervision (stand-in Basalt process) -----------------------------------------

def _spawn(tmp_path, mode, delay="0.3"):
    port = free_port()
    runtime = catalog(port, env={"FAKE_BASALT_MODE": mode, "FAKE_BASALT_DELAY": delay}).runtimes["basalt"]
    preset = runtime.presets["ds41"]
    values, gpus = resolve_settings(BASALT, preset, {}, None)
    supervisor = ProcessSupervisor(tmp_path, poll_seconds=0.1)
    return supervisor, runtime, supervisor.spawn("op-1", runtime, preset, values, gpus)


def test_supervisor_starts_waits_and_stops_a_process(tmp_path):
    supervisor, runtime, handle = _spawn(tmp_path, "ok")
    try:
        assert supervisor.wait_ready(handle, runtime, 20)
        assert supervisor.model_status(runtime) == "loaded"
        assert supervisor.adopt(handle.worker_id, handle.port) is not None
        written = json.loads((tmp_path / "launch" / "op-1" / "basalt-config.json").read_text())
        assert written["models"][0]["resident-budget-gib"] == 48
    finally:
        supervisor.stop(handle)
    assert supervisor.wait_exited(handle, 10)
    assert supervisor.adopt(handle.worker_id, handle.port) is None
    assert "order=PCI_BUS_ID" in (tmp_path / "logs" / "basalt-op-1.log").read_text()


def test_supervisor_reports_an_early_exit_with_the_log(tmp_path):
    supervisor, runtime, handle = _spawn(tmp_path, "exit")
    with pytest.raises(WorkerFailed, match="resident-budget-gib 40") as failure:
        supervisor.wait_ready(handle, runtime, 20)
    assert failure.value.code == "WORKER_EXITED"


def test_supervisor_reports_a_failed_model(tmp_path):
    supervisor, runtime, handle = _spawn(tmp_path, "fail")
    try:
        with pytest.raises(WorkerFailed) as failure:
            supervisor.wait_ready(handle, runtime, 20)
        assert failure.value.code == "WORKER_FAILED"
    finally:
        supervisor.stop(handle)
        supervisor.wait_exited(handle, 10)


def test_supervisor_never_adopts_garbage_ids(tmp_path):
    supervisor = ProcessSupervisor(tmp_path)
    assert supervisor.adopt("not-a-pid", 8160) is None
    assert supervisor.adopt("pid:1:0.000", 8160) is None


def test_description_comes_from_the_plugin_unless_the_catalog_overrides_it():
    data = catalog_data(8160)
    plain = describe_runtime("basalt", parse_catalog(data).runtimes["basalt"], host()["gpus"])
    assert plain["description"] == BASALT.description
    assert plain["presets"]["ds41"]["description"] is None
    data["runtimes"]["basalt"]["description"] = "Our main chat model."
    data["runtimes"]["basalt"]["presets"]["ds41"]["description"] = "Best for long coding sessions."
    custom = describe_runtime("basalt", parse_catalog(data).runtimes["basalt"], host()["gpus"])
    assert custom["description"] == "Our main chat model."
    assert custom["presets"]["ds41"]["description"] == "Best for long coding sessions."


@pytest.mark.parametrize("kind", plugin_kinds())
def test_every_plugin_describes_itself(kind):
    assert get_plugin(kind).description.strip()
