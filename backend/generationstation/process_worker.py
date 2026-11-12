"""Supervises real runtime processes that Generation Station starts and owns, for any plugin."""
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .plugins import get_plugin


@dataclass
class ProcessHandle:
    worker_id: str
    pid: int
    create_time: float
    port: int
    log_path: Path | None = None
    process: subprocess.Popen | None = field(default=None, repr=False)

    @staticmethod
    def make_id(pid, create_time):
        return f"pid:{pid}:{create_time:.3f}"

    @staticmethod
    def parse_id(worker_id):
        try:
            kind, pid, created = worker_id.split(":")
            if kind != "pid":
                return None
            return int(pid), float(created)
        except (AttributeError, ValueError):
            return None


class WorkerFailed(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def log_tail(path, lines=8):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    rows = [row.strip() for row in text.replace("\r", "\n").split("\n") if row.strip()]
    return "\n".join(rows[-lines:])


class ProcessSupervisor:
    """Starts a plugin's server process, waits on the plugin's readiness probe, and stops the tree."""

    worker_type = "runtime"

    def __init__(self, runtime_dir: Path, poll_seconds=2.0, base_env=None):
        self.runtime_dir = Path(runtime_dir)
        self.poll_seconds = poll_seconds
        self.base_env = base_env

    def spawn(self, operation_id, runtime, preset, values, gpus):
        plugin = get_plugin(runtime.kind)
        launch_dir = self.runtime_dir / "launch" / operation_id
        log_dir = self.runtime_dir / "logs"
        launch_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        base_env = dict(os.environ) if self.base_env is None else dict(self.base_env)
        spec = plugin.launch(runtime, preset, values, gpus, base_env, launch_dir)
        for name, content in spec.files.items():
            target = (launch_dir / name).resolve()
            if launch_dir.resolve() not in target.parents:
                raise WorkerFailed("WORKER_START_FAILED", f"Plugin file {name!r} is outside its launch folder.")
            target.write_text(content, encoding="utf-8")
        log_path = log_dir / f"{runtime.kind}-{operation_id}.log"
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        with open(log_path, "wb") as log:
            process = subprocess.Popen(spec.argv, cwd=spec.cwd or None, env=spec.env, stdout=log,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        try:
            created = psutil.Process(process.pid).create_time()
        except psutil.Error:
            created = 0.0
        return ProcessHandle(ProcessHandle.make_id(process.pid, created), process.pid, created,
                             runtime.port, log_path, process)

    def adopt(self, worker_id, port):
        """Re-attach to a process this service started before a restart, if it is still the same one."""
        parsed = ProcessHandle.parse_id(worker_id)
        if not parsed:
            return None
        pid, created = parsed
        try:
            proc = psutil.Process(pid)
            if abs(proc.create_time() - created) > 0.01 or not proc.is_running():
                return None
        except psutil.Error:
            return None
        return ProcessHandle(worker_id, pid, created, port)

    def is_alive(self, handle):
        if handle.process is not None:
            return handle.process.poll() is None
        try:
            proc = psutil.Process(handle.pid)
            return proc.is_running() and abs(proc.create_time() - handle.create_time) <= 0.01 \
                and proc.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False

    def model_status(self, runtime):
        return get_plugin(runtime.kind).probe(runtime)

    def wait_ready(self, handle, runtime, timeout_seconds, cancelled=lambda: False):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if cancelled():
                raise WorkerFailed("SERVICE_STOPPING", "The service stopped while the model was loading.")
            if not self.is_alive(handle):
                tail = log_tail(handle.log_path) if handle.log_path else ""
                raise WorkerFailed("WORKER_EXITED", f"{runtime.name} exited before it finished loading."
                                   + (f"\n{tail}" if tail else ""))
            status = self.model_status(runtime)
            if status == "loaded":
                return True
            if status == "failed":
                tail = log_tail(handle.log_path) if handle.log_path else ""
                raise WorkerFailed("WORKER_FAILED", f"{runtime.name} reported that the model failed to load."
                                   + (f"\n{tail}" if tail else ""))
            time.sleep(self.poll_seconds)
        return False

    def stop(self, handle):
        """Terminate the owned process tree (servers often run their engine as a child)."""
        try:
            root = psutil.Process(handle.pid)
            if abs(root.create_time() - handle.create_time) > 0.01:
                return  # PID reused by an unrelated process; never touch it.
            procs = [root, *root.children(recursive=True)]
        except psutil.Error:
            return
        for proc in procs:
            try:
                proc.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(procs, timeout=5)
        for proc in alive:
            try:
                proc.kill()
            except psutil.Error:
                pass

    def wait_exited(self, handle, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self.is_alive(handle) and not port_in_use(handle.port):
                if handle.process is not None:
                    handle.process.wait(timeout=1)
                return True
            time.sleep(0.25)
        return False
