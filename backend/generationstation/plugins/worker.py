"""Shared base for plugins whose model runs in a worker from `workers/` (the gs_worker protocol).

Each such model gets its own Python environment (set by `python` in runtimes.json), so model
dependencies never mix with Generation Station's or with each other's.
"""
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from .base import BasePreset, BaseRuntime, LaunchSpec, RuntimePlugin

WORKERS_DIR = Path(__file__).resolve().parents[3] / "workers"


class WorkerPreset(BasePreset):
    # Owner-set model options passed to the worker (model folders, precision). Not user-editable.
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class WorkerRuntime(BaseRuntime):
    python: str = Field(min_length=1, description="python.exe of this model's own environment.")
    output_dir: str = Field(min_length=1, description="Where finished files are kept.")
    env: dict[str, str] = Field(default_factory=dict)
    worker_script: str | None = Field(default=None, description="Override the plugin's worker; for tests.")
    ready_timeout_seconds: float = Field(default=900, gt=0, le=7200)
    presets: dict[str, WorkerPreset] = Field(min_length=1)


def _request(method, url, payload=None, timeout=5):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8", errors="replace"))
        except ValueError:
            return exc.code, {}
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


class WorkerPlugin(RuntimePlugin):
    """Subclass, set kind/title/runtime_model/worker_script/inputs, and you have a model plugin."""

    worker_script: ClassVar[str]

    def script_path(self, runtime: WorkerRuntime) -> Path:
        return Path(runtime.worker_script) if runtime.worker_script else WORKERS_DIR / self.worker_script

    def launch(self, runtime, preset, values, gpus, base_env, launch_dir: Path):
        config = {"port": runtime.port, "output_dir": str(self.output_dir(runtime)), "options": preset.options,
                  "settings": values, "gpus": gpus, "launch_dir": str(launch_dir)}
        env = dict(base_env)
        env.update(runtime.env)
        # The worker sees only the chosen cards, numbered from 0, in nvidia-smi order.
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpus)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(WORKERS_DIR)
        config_path = Path(launch_dir) / "worker-config.json"
        return LaunchSpec(argv=[runtime.python, str(self.script_path(runtime)), "--config", str(config_path)],
                          env=env, cwd=str(WORKERS_DIR),
                          files={"worker-config.json": json.dumps(config, indent=2)})

    def probe(self, runtime):
        status, body = _request("GET", f"http://127.0.0.1:{runtime.port}/health", timeout=3)
        if status != 200 or not isinstance(body, dict):
            return None
        return {"loaded": "loaded", "failed": "failed"}.get(body.get("status"), "loading")

    def output_dir(self, runtime):
        return Path(runtime.output_dir)

    def submit(self, runtime, job_id, inputs):
        status, body = _request("POST", f"http://127.0.0.1:{runtime.port}/generate",
                                {"job_id": job_id, "inputs": inputs}, timeout=10)
        if status != 202 or not isinstance(body, dict):
            message = (body or {}).get("error") if isinstance(body, dict) else None
            raise RuntimeError(message or f"The worker did not accept the job (HTTP {status}).")
        return body

    def cancel(self, runtime, job_id):
        status, body = _request("POST", f"http://127.0.0.1:{runtime.port}/jobs/{job_id}/cancel", {}, timeout=5)
        if status == 404 and isinstance(body, dict) and body.get("error") == "job not found":
            return {"status": "missing"}  # a worker that predates cancel answers "not found" instead: None
        return body if status == 200 and isinstance(body, dict) else None

    def job_status(self, runtime, job_id):
        status, body = _request("GET", f"http://127.0.0.1:{runtime.port}/jobs/{job_id}", timeout=5)
        return body if status == 200 and isinstance(body, dict) else None
