import threading
import time
from types import SimpleNamespace

import pytest

from generationstation import telemetry
from generationstation.config import Settings
from generationstation.telemetry import Collector, Monitor, environment_scope, memory_values


def settings(**overrides):
    values = {"database_url": "postgresql+psycopg://test:test@localhost/test",
              "api_token": "t" * 48}
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("values", [
    (0, 0, 0), (-1, 0, 0), (10, 11, 1), (10, 1, -1),
    (10.0, 5, 5), (10, True, 5), (10, 5, False),
])
def test_invalid_memory_counters_are_rejected(values):
    with pytest.raises(ValueError):
        memory_values(*values)


def test_first_sample_is_explicitly_unknown_and_stale():
    monitor = Monitor(settings())
    data = monitor.snapshot()
    assert data["ram"] is None
    assert data["stale"] is True
    assert data["status"] == "stale"
    assert data["age_seconds"] is None
    assert data["loading_enabled"] is False


def test_collector_exception_produces_unknown_stale_or_degraded_snapshot():
    class BrokenCollector:
        def sample(self):
            raise RuntimeError("secret driver details")

        def close(self):
            pass

    monitor = Monitor(settings(), collector=BrokenCollector())
    monitor.collect_once()
    data = monitor.snapshot()
    assert data["ram"] is None
    assert data["ram_error"] == "Host telemetry failed."
    assert data["gpu_error"] == "Host telemetry failed."
    assert "secret driver details" not in repr(data)
    assert data["loading_enabled"] is False


def test_sample_age_includes_time_spent_inside_provider():
    now = [10.0]

    class SlowCollector:
        def sample(self):
            now[0] += 4.5
            return {"ram": {"total_bytes": 10, "available_bytes": 8, "used_bytes": 2},
                    "ram_error": None, "gpus": [], "gpu_error": None}

        def close(self):
            pass

    monitor = Monitor(settings(stale_after_seconds=3), collector=SlowCollector(), clock=lambda: now[0])
    monitor.collect_once()
    data = monitor.snapshot()
    assert data["age_seconds"] == pytest.approx(4.5)
    assert data["stale"] is True
    assert data["status"] == "stale"


def test_stop_returns_within_bound_when_provider_hangs():
    entered = threading.Event()
    release = threading.Event()

    class HangingCollector:
        def sample(self):
            entered.set()
            release.wait(timeout=5)
            return {"ram": None, "ram_error": "unknown", "gpus": [], "gpu_error": "unknown"}

        def close(self):
            pass

    monitor = Monitor(settings(), collector=HangingCollector())
    monitor.start()
    assert entered.wait(timeout=1)
    started = time.monotonic()
    monitor.stop()
    elapsed = time.monotonic() - started
    release.set()
    monitor.thread.join(timeout=1)
    assert elapsed < 2.5
    assert not monitor.thread.is_alive()


def test_per_gpu_failure_does_not_hide_later_gpu(monkeypatch):
    class FakeNvml:
        def nvmlInit(self):
            pass

        def nvmlDeviceGetCount(self):
            return 2

        def nvmlDeviceGetHandleByIndex(self, index):
            if index == 0:
                raise RuntimeError("one device vanished")
            return index

        def nvmlDeviceGetName(self, handle):
            return b"RTX test"

        def nvmlDeviceGetUUID(self, handle):
            return b"GPU-good"

        def nvmlDeviceGetMemoryInfo(self, handle):
            return SimpleNamespace(total=100, free=60, used=40)

        def nvmlShutdown(self):
            pass

    monkeypatch.setattr(telemetry, "pynvml", FakeNvml())
    result = Collector().sample()
    assert result["gpu_error"] is None
    assert result["gpus"][0]["memory"] is None
    assert result["gpus"][0]["error"]
    assert result["gpus"][1]["id"] == "GPU-good"
    assert result["gpus"][1]["memory"] == {
        "total_bytes": 100, "available_bytes": 60, "used_bytes": 40,
    }


def test_malformed_gpu_memory_is_unknown_for_only_that_gpu(monkeypatch):
    class FakeNvml:
        def nvmlInit(self):
            pass

        def nvmlDeviceGetCount(self):
            return 1

        def nvmlDeviceGetHandleByIndex(self, index):
            return index

        def nvmlDeviceGetName(self, handle):
            return "GPU"

        def nvmlDeviceGetUUID(self, handle):
            return "GPU-0"

        def nvmlDeviceGetMemoryInfo(self, handle):
            return SimpleNamespace(total=100, free=float("nan"), used=20)

    monkeypatch.setattr(telemetry, "pynvml", FakeNvml())
    result = Collector().sample()
    assert result["gpus"][0]["memory"] is None
    assert result["gpus"][0]["error"] is not None


def test_device_absence_and_nvml_unavailable_are_reported_as_unknown(monkeypatch):
    class NoGpuNvml:
        def nvmlInit(self):
            pass

        def nvmlDeviceGetCount(self):
            return 0

    monkeypatch.setattr(telemetry, "apple_unified_gpu", lambda ram: None)  # these tests run on Macs too
    monkeypatch.setattr(telemetry, "pynvml", NoGpuNvml())
    assert Collector().sample()["gpu_error"] == "No NVIDIA GPU was reported by NVML."

    class BrokenNvml:
        def nvmlInit(self):
            raise RuntimeError("driver details")

    monkeypatch.setattr(telemetry, "pynvml", BrokenNvml())
    assert "unavailable" in Collector().sample()["gpu_error"]


def test_an_apple_silicon_mac_reports_its_shared_memory_as_one_gpu(monkeypatch):
    class BrokenNvml:
        def nvmlInit(self):
            raise RuntimeError("no NVIDIA driver")

    monkeypatch.setattr(telemetry, "pynvml", BrokenNvml())
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(telemetry.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(telemetry, "apple_chip_name", lambda: "Apple M5 Max")
    result = Collector().sample()
    assert result["gpu_error"] is None and len(result["gpus"]) == 1
    gpu = result["gpus"][0]
    assert gpu["id"] == "apple-unified-memory" and gpu["index"] == 0 and gpu["error"] is None
    assert gpu["name"] == "Apple M5 Max (unified memory)" and gpu["memory"] == result["ram"]


def test_only_apple_silicon_gets_the_shared_memory_gpu(monkeypatch):
    ram = memory_values(100, 50, 50)
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(telemetry.platform, "machine", lambda: "x86_64")
    assert telemetry.apple_unified_gpu(ram) is None  # an Intel Mac has no shared-memory GPU to report
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(telemetry.platform, "machine", lambda: "arm64")
    assert telemetry.apple_unified_gpu(ram) is None
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Darwin")
    assert telemetry.apple_unified_gpu(None) is None  # no RAM reading, no device


def test_on_a_mac_used_memory_is_everything_that_is_not_available(monkeypatch):
    mem = SimpleNamespace(total=64 * 2**30, available=30 * 2**30, used=13 * 2**30)  # psutil's used leaves out mapped weights
    monkeypatch.setattr(telemetry.psutil, "virtual_memory", lambda: mem)
    monkeypatch.setattr(telemetry, "apple_unified_gpu", lambda ram: None)
    monkeypatch.setattr(telemetry, "darwin_vm_pages", lambda: None)  # the kernel's counters are not readable here
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Darwin")
    assert Collector().sample()["ram"]["used_bytes"] == 34 * 2**30
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Windows")
    assert Collector().sample()["ram"]["used_bytes"] == 13 * 2**30


def fake_pages(**gib):
    """The kernel's counters for a Mac with 1 GiB pages, in GiB."""
    stats = telemetry._VMStatistics64()
    for name, value in gib.items():
        setattr(stats, name, value)
    return lambda: (stats, 2**30)


def test_a_macs_cached_files_are_available_and_only_app_wired_and_compressed_memory_is_used():
    # 10 GiB of application memory (1 of it purgeable), 4 wired, 2 compressed; 5 GiB of cached files, 7 inactive.
    pages = fake_pages(internal=10, purgeable=1, wire=4, compressor=2, external=5, inactive=7)
    assert telemetry.darwin_memory(64 * 2**30, pages) == (49 * 2**30, 15 * 2**30)


def test_a_models_memory_mapped_weights_are_cache_not_used_memory():
    # 27 GiB of a running model's mapped file is `external`: the process's own memory is the only part that is used.
    idle = fake_pages(internal=10, wire=4, compressor=2, external=5)
    loaded = fake_pages(internal=22, wire=4, compressor=2, external=32)
    assert telemetry.darwin_memory(64 * 2**30, idle)[1] == 16 * 2**30
    assert telemetry.darwin_memory(64 * 2**30, loaded)[1] == 28 * 2**30  # 12 GiB more, not 39


def test_unreadable_or_impossible_mac_counters_fall_back():
    assert telemetry.darwin_memory(64 * 2**30, lambda: None) is None
    assert telemetry.darwin_memory(8 * 2**30, fake_pages(internal=10, wire=4)) is None  # more used than exists


def test_monitor_exposes_configured_host_role_and_detected_runtime_scope(monkeypatch):
    monkeypatch.setattr(telemetry.platform, "release", lambda: "11")
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(telemetry.Path, "exists", lambda self: False)
    monitor = Monitor(settings(host_role="desktop", host_label="Generation Station desktop"))
    assert monitor.identity["role"] == "desktop"
    assert monitor.identity["label"] == "Generation Station desktop"
    assert monitor.identity["os"] == "Windows"
    assert monitor.identity["scope"] == "host"


@pytest.mark.parametrize(("release", "expected"), [
    ("Microsoft", "wsl"), ("5.15.90.1-microsoft-standard-WSL2", "wsl"), ("11", "host"),
])
def test_environment_scope_recognizes_native_windows_and_wsl(monkeypatch, release, expected):
    monkeypatch.setattr(telemetry.platform, "release", lambda: release)
    monkeypatch.setattr(telemetry.Path, "exists", lambda self: False)
    assert environment_scope() == expected


def test_scope_marks_container_runtime(monkeypatch):
    class FakePath:
        def __init__(self, value):
            self.value = value

        def exists(self):
            return self.value == "/.dockerenv"

    monkeypatch.setattr(telemetry.platform, "release", lambda: "linux")
    monkeypatch.setattr(telemetry, "Path", FakePath)
    assert environment_scope() == "container"


def test_stale_window_must_exceed_collection_interval():
    with pytest.raises(ValueError, match="stale_after_seconds"):
        settings(sample_interval_seconds=5, stale_after_seconds=5)
