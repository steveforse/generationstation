import os
import sys

import psutil
import pytest

from generationstation import process_memory
from generationstation.process_memory import VRAM_UNAVAILABLE, ProcessMemoryCollector, process_tree
from generationstation.telemetry import Monitor
from tests.test_telemetry import settings

GPU_A = {"index": 0, "id": "GPU-a", "error": None}
GPU_B = {"index": 1, "id": "GPU-b", "error": None}
ME = os.getpid()
ME_CREATED = psutil.Process(ME).create_time()


def windows(process_vram, luid_buses=None):
    return ProcessMemoryCollector(platform="win32", nvml_bus=lambda index: {0: 1, 1: 2}[index],
                                  luid_buses=lambda: luid_buses or {"luid_0x0_0x1": 1, "luid_0x0_0x2": 2},
                                  process_vram=lambda: process_vram)


def test_nothing_owned_samples_nothing():
    def explode():
        raise AssertionError("should not query counters")
    assert ProcessMemoryCollector(platform="win32", process_vram=explode, luid_buses=explode).sample({}, [GPU_A]) == {}


def test_attributes_vram_to_the_owned_tree_and_maps_adapters_by_pci_bus():
    usage = windows({(ME, "luid_0x0_0x1"): 5 * 2**30, (ME, "luid_0x0_0x2"): 2**30, (ME + 999_999, "luid_0x0_0x1"): 7 * 2**30})
    result = usage.sample({"basalt": (ME, ME_CREATED)}, [GPU_A, GPU_B])["basalt"]
    assert result["gpus"] == {"GPU-a": 5 * 2**30, "GPU-b": 2**30}  # another process's VRAM is not counted
    assert result["ram_bytes"] > 0 and result["error"] is None


def test_adapter_luids_match_regardless_of_hex_case():
    usage = windows({(ME, "luid_0x0_0x1A"): 2**30}, luid_buses={"luid_0x0_0x1a": 1})
    assert usage.sample({"m": (ME, ME_CREATED)}, [GPU_A])["m"]["gpus"] == {"GPU-a": 2**30}


def test_adapters_without_a_matching_gpu_are_ignored():
    usage = windows({(ME, "luid_0x0_0x9"): 2**30, (ME, "luid_0x0_0x1"): 3}, luid_buses={"luid_0x0_0x1": 1, "luid_0x0_0x9": 7})
    assert usage.sample({"m": (ME, ME_CREATED)}, [GPU_A])["m"]["gpus"] == {"GPU-a": 3}


def test_counter_failure_reports_vram_unknown_but_keeps_ram():
    def broken():
        raise OSError("no counters")
    usage = ProcessMemoryCollector(platform="win32", nvml_bus=lambda index: 1, luid_buses=lambda: {"luid_0x0_0x1": 1}, process_vram=broken)
    result = usage.sample({"m": (ME, ME_CREATED)}, [GPU_A])["m"]
    assert result["error"] == VRAM_UNAVAILABLE and result["gpus"] == {} and result["ram_bytes"] > 0


def test_reused_pid_is_not_measured():
    assert process_tree(ME, ME_CREATED + 1000) == []
    result = windows({(ME, "luid_0x0_0x1"): 2**30}).sample({"m": (ME, ME_CREATED + 1000)}, [GPU_A])["m"]
    assert result["ram_bytes"] is None and result["gpus"] == {}


def test_monitor_publishes_per_model_memory_without_failing_host_telemetry():
    class HostCollector:
        def sample(self):
            return {"ram": None, "ram_error": None, "gpus": [GPU_A], "gpu_error": None}

    class ProcessCollector:
        def __init__(self):
            self.fail = False

        def sample(self, owned, gpus, helpers=None):
            if self.fail:
                raise RuntimeError("boom")
            return {model_id: {"ram_bytes": 1, "gpus": {gpus[0]["id"]: 2}, "error": None} for model_id in owned}

    processes = ProcessCollector()
    monitor = Monitor(settings(), collector=HostCollector(), process_collector=processes)
    monitor.watch_processes(lambda: {"basalt": (ME, ME_CREATED)})
    monitor.collect_once()
    assert monitor.snapshot()["model_memory"] == {"basalt": {"ram_bytes": 1, "gpus": {"GPU-a": 2}, "error": None}}
    processes.fail = True
    monitor.collect_once()
    snapshot = monitor.snapshot()
    assert snapshot["model_memory"] == {} and snapshot["gpus"] == [GPU_A]


def test_a_model_running_in_wsl_is_credited_with_the_vm_process_memory():
    """Drama 3 runs inside WSL; Windows reports that GPU memory under vmwp, which counts for the model (not its RAM)."""
    vm = ME + 424_242
    usage = ProcessMemoryCollector(platform="win32", nvml_bus=lambda index: {0: 1, 1: 2}[index],
                                   luid_buses=lambda: {"luid_0x0_0x1": 1, "luid_0x0_0x2": 2},
                                   process_vram=lambda: {(vm, "luid_0x0_0x1"): 24 * 2**30, (ME, "luid_0x0_0x1"): 2**20},
                                   pids_named=lambda names: {vm} if "vmwp" in names else set())
    result = usage.sample({"fish_drama3": (ME, ME_CREATED), "other": (ME, ME_CREATED)}, [GPU_A, GPU_B],
                          {"fish_drama3": ("vmwp",), "stopped_model": ("vmwp",)})
    assert result["fish_drama3"]["gpus"] == {"GPU-a": 24 * 2**30 + 2**20}
    assert result["other"]["gpus"] == {"GPU-a": 2**20}  # only the model that declares the helper
    assert "stopped_model" not in result


def test_a_macs_process_memory_is_its_physical_footprint_not_its_resident_size(monkeypatch):
    class Proc:
        pid = 4242

        def memory_info(self):
            return type("Info", (), {"rss": 600 * 2**20})()

    monkeypatch.setattr(process_memory, "darwin_footprint", lambda pid: 16 * 2**30 if pid == 4242 else None)
    assert process_memory.tree_ram_bytes([Proc()]) == 16 * 2**30
    monkeypatch.setattr(process_memory, "darwin_footprint", lambda pid: None)  # any other host: the working set
    assert process_memory.tree_ram_bytes([Proc()]) == 600 * 2**20


@pytest.mark.skipif(sys.platform != "darwin", reason="reads macOS's libproc")
def test_the_footprint_of_a_live_process_is_at_least_its_resident_size():
    footprint = process_memory.darwin_footprint(os.getpid())
    assert footprint is not None and footprint >= psutil.Process().memory_info().rss * 0.5
