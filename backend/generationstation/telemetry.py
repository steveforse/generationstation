"""Samples this process's host. Never substitutes the planned desktop inventory."""
import copy
import platform
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import pynvml

from .process_memory import ProcessMemoryCollector


def memory_values(total: int, available: int, used: int) -> dict:
    counters = (total, available, used)
    if any(type(value) is not int for value in counters):
        raise ValueError("Memory counters must be integers")
    if total <= 0 or not 0 <= available <= total or not 0 <= used <= total:
        raise ValueError("Invalid memory counters")
    return {"total_bytes": total, "available_bytes": available, "used_bytes": used}


def environment_scope() -> str:
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        return "wsl"
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "container"
    return "host"


class Collector:
    def __init__(self):
        self.nvml_ready = False

    def sample(self) -> dict:
        result = {"ram": None, "ram_error": None, "gpus": [], "gpu_error": None}
        try:
            ram = psutil.virtual_memory()
            result["ram"] = memory_values(ram.total, ram.available, ram.used)
        except Exception:  # noqa: BLE001 - isolate provider failures as unknown telemetry.
            result["ram_error"] = "System memory telemetry is unavailable."
        try:
            if not self.nvml_ready:
                pynvml.nvmlInit()
                self.nvml_ready = True
            count = pynvml.nvmlDeviceGetCount()
            if count == 0:
                result["gpu_error"] = "No NVIDIA GPU was reported by NVML."
            for index in range(count):
                # index is NVML (PCI bus) order; runtimes are started with the same CUDA order.
                gpu = {"id": f"unknown-{index}", "index": index, "name": f"GPU {index}",
                       "memory": None, "error": None}
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                    name = pynvml.nvmlDeviceGetName(handle)
                    device_id = pynvml.nvmlDeviceGetUUID(handle)
                    gpu["name"] = name.decode() if isinstance(name, bytes) else name
                    gpu["id"] = device_id.decode() if isinstance(device_id, bytes) else device_id
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    gpu["memory"] = memory_values(mem.total, mem.free, mem.used)
                except Exception:  # noqa: BLE001 - continue collecting other physical GPUs.
                    gpu["error"] = "GPU identity or VRAM accounting is unavailable for this device/driver."
                result["gpus"].append(gpu)
        except Exception:  # noqa: BLE001 - NVML errors are surfaced as unknown capacity.
            result["gpu_error"] = "NVIDIA telemetry is unavailable. Check the host driver and NVML support."
        return result

    def close(self):
        if self.nvml_ready:
            try:
                pynvml.nvmlShutdown()
            except pynvml.NVMLError:
                pass


class Monitor:
    def __init__(self, settings, collector=None, clock=time.monotonic, process_collector=None):
        self.settings = settings
        self.collector = collector or Collector()
        self.process_collector = process_collector or ProcessMemoryCollector()
        # Returns {model_id: (pid, create_time)} for the model processes this service owns.
        self.owned_processes = dict
        self.clock = clock
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.sample_data = None
        self.sample_time = None
        self.sample_id = 0
        self.thread = None
        self.identity = {
            "hostname": socket.gethostname(), "os": platform.system(),
            "label": settings.host_label, "role": settings.host_role, "scope": environment_scope(),
        }

    def collect_once(self):
        # Age includes collection time: a hung/slow provider cannot create a fresh-looking sample.
        started = self.clock()
        observed_at = datetime.now(timezone.utc).isoformat()
        try:
            data = self.collector.sample()
        except Exception:  # noqa: BLE001 - keep monitor alive and report failed collection.
            data = {"ram": None, "ram_error": "Host telemetry failed.", "gpus": [],
                    "gpu_error": "Host telemetry failed."}
        # Display only; admission never reads these per-model figures.
        try:
            model_memory = self.process_collector.sample(self.owned_processes(), data.get("gpus") or [])
        except Exception:  # noqa: BLE001 - per-model usage failing must not break host telemetry.
            model_memory = {}
        data = {**data, "model_memory": model_memory}
        with self.lock:
            self.sample_id += 1
            self.sample_time = started
            self.sample_data = {**data, "observed_at": observed_at, "sequence": self.sample_id}

    def snapshot(self) -> dict:
        with self.lock:
            data = copy.deepcopy(self.sample_data)
            age = None if self.sample_time is None else max(0, self.clock() - self.sample_time)
        stale = age is None or age >= self.settings.stale_after_seconds
        if data is None:
            data = {"ram": None, "ram_error": "Waiting for first sample.", "gpus": [],
                    "gpu_error": None, "observed_at": None, "sequence": 0, "model_memory": {}}
        return {
            **data, "host": self.identity, "age_seconds": age, "stale": stale,
            "stale_after_seconds": self.settings.stale_after_seconds,
            "status": "stale" if stale else ("degraded" if data["ram_error"] or data["gpu_error"]
                      or any(g["error"] for g in data["gpus"]) else "live"),
            "loading_enabled": False,
            "loading_reason": "Model loading will be available after capacity checks and a runtime are verified.",
        }

    def watch_processes(self, owned_processes):
        self.owned_processes = owned_processes

    def start(self):
        def run():
            try:
                while not self.stop_event.is_set():
                    self.collect_once()
                    self.stop_event.wait(self.settings.sample_interval_seconds)
            finally:
                self.collector.close()
        self.thread = threading.Thread(target=run, name="host-telemetry", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
