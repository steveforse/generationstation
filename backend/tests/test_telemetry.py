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

    monkeypatch.setattr(telemetry, "pynvml", NoGpuNvml())
    assert Collector().sample()["gpu_error"] == "No NVIDIA GPU was reported by NVML."

    class BrokenNvml:
        def nvmlInit(self):
            raise RuntimeError("driver details")

    monkeypatch.setattr(telemetry, "pynvml", BrokenNvml())
    assert "unavailable" in Collector().sample()["gpu_error"]


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
    monkeypatch.setattr(telemetry.platform, "release", lambda: "linux")
    monkeypatch.setattr(telemetry.Path, "exists", lambda self: str(self) == "/.dockerenv")
    assert environment_scope() == "container"


def test_stale_window_must_exceed_collection_interval():
    with pytest.raises(ValueError, match="stale_after_seconds"):
        settings(sample_interval_seconds=5, stale_after_seconds=5)
