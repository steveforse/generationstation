"""Serialized capacity admission and process-local fake-worker lifecycle."""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

from .plugins import get_plugin
from .process_worker import WorkerFailed, port_in_use
from .runtimes import Catalog, SettingsError, describe_runtime, estimate_requirements, resolve_settings


class IdempotencyConflict(Exception):
    pass


class LifecycleError(Exception):
    def __init__(self, code, message, status_code=409, resources=None, operation_id=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.resources = resources or []
        self.operation_id = operation_id


class FakeHandle:
    """An in-memory handle; this adapter never starts a process or opens model files."""

    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.stopped = False
        self.exited = False


class FakeWorkerAdapter:
    """Fixed M2 simulation adapter. It performs no inference and accepts no command."""

    worker_type = "fake"

    def __init__(self):
        self.spawned = []
        self.stopped = []

    def spawn(self, model_id, profile):
        handle = FakeHandle(str(uuid.uuid4()))
        self.spawned.append((model_id, handle))
        return handle

    def wait_ready(self, handle, timeout_seconds):
        return True

    def stop(self, handle):
        handle.stopped = True
        self.stopped.append(handle.worker_id)

    def wait_exited(self, handle, timeout_seconds):
        handle.exited = True
        return True


def request_fingerprint(action, model_id, profile_id=None):
    raw = json.dumps([action, model_id, profile_id], separators=(",", ":"), ensure_ascii=True,
                     sort_keys=True)
    return sha256(raw.encode("ascii")).hexdigest()


def serialize_operation(operation):
    launch = operation.get("launch")
    return {
        "id": operation["id"], "operation_id": operation["id"], "model_id": operation["model_id"],
        "profile_id": operation.get("profile_id"), "profile_revision": operation.get("profile_revision"),
        "action": operation["action"], "status": operation["status"], "launch": launch,
        "simulation": launch is None, "worker_type": "fake" if launch is None else "runtime",
        "created_at": operation["created_at"].isoformat()
        if hasattr(operation.get("created_at"), "isoformat") else operation.get("created_at"),
        "updated_at": operation["updated_at"].isoformat()
        if hasattr(operation.get("updated_at"), "isoformat") else operation.get("updated_at"),
        "error_code": operation.get("error_code"), "error_message": operation.get("error_message"),
        "refusal": operation.get("refusal"),
    }


class LifecycleManager:
    def __init__(self, store, settings, worker=None, catalog=None, runtime_adapter=None):
        self.store = store
        self.settings = settings
        self.worker = worker or FakeWorkerAdapter()
        self.catalog = catalog if catalog is not None else Catalog()
        self.runtime_adapter = runtime_adapter
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake-worker")
        # Real runtimes load for many minutes; keep them off the fake worker's queue.
        self.runtime_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runtime-worker")
        self.handles = {}
        self.runtime_handles = {}
        self.closed = False
        self.persistence_errors = 0

    # ----- real runtimes -------------------------------------------------------------

    def runtime_catalog(self, host):
        gpus = host.get("gpus") or []
        launches = self.store.latest_launches() if hasattr(self.store, "latest_launches") else {}
        result = []
        for model_id, runtime in self.catalog.runtimes.items():
            entry = describe_runtime(model_id, runtime, gpus)
            entry["last_launch"] = (launches.get(model_id) or {}).get("launch")
            entry["thinking"] = self._thinking(model_id, runtime, entry["last_launch"])
            result.append(entry)
        return result

    def _thinking(self, model_id, runtime, launch):
        """The thinking levels the chat may offer for the model's latest launch (what runs while it is ready)."""
        preset = runtime.presets.get((launch or {}).get("preset")) or runtime.presets.get(runtime.default_preset)
        if preset is None:
            return None
        return self.catalog.plugin(model_id).chat_thinking(preset, (launch or {}).get("gpus") or preset.gpus)

    def sync_catalog(self):
        if self.catalog.runtimes and hasattr(self.store, "sync_runtime_models"):
            self.store.sync_runtime_models([
                {"id": model_id, "name": runtime.name, "workload": runtime.workload}
                for model_id, runtime in self.catalog.runtimes.items()
            ])

    def recover_runtime_processes(self):
        """After a restart: re-adopt ready runtimes that still run; stop orphans of interrupted loads.

        Returns the operation IDs to keep active during restart reconciliation.
        """
        keep = []
        if self.runtime_adapter is None or not hasattr(self.store, "active_runtime_operations"):
            return keep
        for op in self.store.active_runtime_operations():
            runtime = self.catalog.runtimes.get(op["model_id"])
            if runtime is None or not op.get("worker_id"):
                continue
            handle = self.runtime_adapter.adopt(op["worker_id"], runtime.port)
            if handle is None:
                continue
            if op["status"] == "ready" and self.runtime_adapter.model_status(runtime) == "loaded":
                with self.lock:
                    self.runtime_handles[op["model_id"]] = handle
                keep.append(op["id"])
            else:
                # A load or unload that this service no longer supervises: stop the owned process.
                self.runtime_adapter.stop(handle)
                self.runtime_adapter.wait_exited(handle, runtime.stop_timeout_seconds)
        return keep

    def owned_processes(self):
        """{model_id: (pid, create_time)} for the runtime processes this service started or re-adopted."""
        with self.lock:
            return {model_id: (handle.pid, getattr(handle, "create_time", 0.0))
                    for model_id, handle in self.runtime_handles.items() if isinstance(getattr(handle, "pid", None), int)}

    def helper_processes(self):
        """{model_id: process names} for running models whose GPU memory partly sits in other programs."""
        with self.lock:
            running = list(self.runtime_handles)
        helpers = {}
        for model_id in running:
            runtime = self.catalog.runtimes.get(model_id) if self.catalog else None
            plugin = get_plugin(runtime.kind) if runtime else None
            if plugin is not None and plugin.gpu_helpers:
                helpers[model_id] = tuple(plugin.gpu_helpers)
        return helpers

    def refresh_runtime_health(self):
        """Mark a ready runtime failed if its process has exited (crash or external stop)."""
        if self.runtime_adapter is None:
            return
        with self.lock:
            items = list(self.runtime_handles.items())
        if not items:
            return
        states = self.store.runtime_states() if hasattr(self.store, "runtime_states") else {}
        for model_id, handle in items:
            state = states.get(model_id, {})
            if state.get("state") != "ready" or self.runtime_adapter.is_alive(handle):
                continue
            with self.lock:
                if self.runtime_handles.get(model_id) is not handle:
                    continue
                self.runtime_handles.pop(model_id, None)
            operation_id = state.get("active_operation_id")
            if operation_id:
                self.store.update_operation(operation_id, status="failed", error_code="WORKER_EXITED",
                                            error_message="The runtime process exited while it was ready.")

    def _runtime_requirement(self, model_id, preset_key, overrides, gpus, host):
        """Resolve a start request to (runtime, preset key, preset, values, gpus, ram bytes, {gpu id: bytes})."""
        runtime = self.catalog.runtimes.get(model_id)
        if runtime is None or self.runtime_adapter is None:
            raise LifecycleError("MODEL_NOT_FOUND", "No configured runtime has that ID.", 404)
        preset = runtime.presets.get(preset_key or runtime.default_preset)
        if preset is None:
            raise LifecycleError("PRESET_NOT_FOUND", "That model choice is not configured.", 422)
        preset_key = preset_key or runtime.default_preset
        plugin = self.catalog.plugin(model_id)
        try:
            values, chosen_gpus = resolve_settings(plugin, preset, overrides, gpus)
            requirement_ram, requirement_gpu = estimate_requirements(plugin, runtime, preset, values, chosen_gpus,
                                                                     host.get("gpus") or [])
        except SettingsError as exc:
            raise LifecycleError("SETTINGS_INVALID", " ".join(exc.errors), 422,
                                 resources=[{"error": e} for e in exc.errors]) from exc
        return runtime, preset_key, preset, values, chosen_gpus, requirement_ram, requirement_gpu

    def estimate_runtime(self, model_id, preset_key, overrides, gpus, host):
        """What a start with these choices would ask admission for. Changes nothing; display only.

        The browser compares this with live telemetry; the start request is still checked independently.
        """
        _, _, _, _, _, requirement_ram, requirement_gpu = self._runtime_requirement(model_id, preset_key, overrides,
                                                                                   gpus, host)
        reserved_ram, reserved_gpu = 0, {}
        reservations = self.store.active_reservations() if hasattr(self.store, "active_reservations") else []
        for reservation in reservations:
            reserved_ram += reservation.get("ram_bytes") or 0
            for device_id, amount in (reservation.get("gpu_vram_bytes_by_id") or {}).items():
                reserved_gpu[device_id] = reserved_gpu.get(device_id, 0) + amount
        return {"ram_bytes": requirement_ram, "gpu_vram_bytes_by_id": requirement_gpu,
                "ram_headroom_bytes": self.settings.ram_headroom_bytes,
                "gpu_headroom_bytes": self.settings.gpu_headroom_bytes,
                "reserved_ram_bytes": reserved_ram, "reserved_gpu_vram_bytes_by_id": reserved_gpu}

    def create_runtime_load(self, model_id, preset_key, overrides, gpus, idempotency_key, host):
        runtime, preset_key, preset, values, chosen_gpus, requirement_ram, requirement_gpu = \
            self._runtime_requirement(model_id, preset_key, overrides, gpus, host)
        launch = {"preset": preset_key, "settings": values, "gpus": chosen_gpus}
        fingerprint = request_fingerprint("load", model_id, launch)
        with self.lock:
            self._ensure_open()
            existing = self.store.find_idempotent_operation(idempotency_key) \
                if hasattr(self.store, "find_idempotent_operation") else None
            if existing is None and model_id not in self.runtime_handles and port_in_use(runtime.port):
                raise LifecycleError(
                    "PORT_IN_USE",
                    f"Something is already serving on port {runtime.port}, probably {runtime.name} started "
                    "outside Generation Station. Stop it there first (for example basalt-stop).", 409)
            result = self.store.create_runtime_load_operation(
                model_id=model_id, launch=launch,
                requirement={"ram_bytes": requirement_ram, "gpu_vram_bytes_by_id": requirement_gpu},
                idempotency_key=idempotency_key, fingerprint=fingerprint, host=host,
                ram_headroom_bytes=self.settings.ram_headroom_bytes,
                gpu_headroom_bytes=self.settings.gpu_headroom_bytes,
            )
            if result.get("idempotency_conflict"):
                raise IdempotencyConflict("The idempotency key was already used for a different request.")
            operation = result.get("operation")
            if result.get("missing_model") or operation is None:
                raise LifecycleError("MODEL_NOT_FOUND", "The model does not exist.", 404)
            if operation["status"] == "refused":
                refusal = operation["refusal"] or {}
                raise LifecycleError(refusal.get("code", "LOAD_REFUSED"), refusal.get("message", "Load refused."),
                                     resources=refusal.get("resources", []), status_code=409,
                                     operation_id=operation["id"])
            if not result.get("existing"):
                try:
                    self.runtime_executor.submit(self._run_runtime_load, operation["id"], model_id,
                                                 runtime, preset, values, chosen_gpus)
                except RuntimeError:
                    self.store.update_operation(operation["id"], status="failed", error_code="WORKER_START_FAILED",
                                                error_message="The runtime could not be scheduled.")
                    raise LifecycleError("WORKER_START_FAILED", "The runtime could not be scheduled.", 503)
            return serialize_operation(operation)

    def _run_runtime_load(self, operation_id, model_id, runtime, preset, values, gpus):
        adapter = self.runtime_adapter
        if self.closed:
            self.store.update_operation(operation_id, status="failed", error_code="SERVICE_STOPPING",
                                        error_message="The service stopped before the runtime started.")
            return
        handle = None
        try:
            handle = adapter.spawn(operation_id, runtime, preset, values, gpus)
            with self.lock:
                self.runtime_handles[model_id] = handle
            self.store.update_operation(operation_id, status="loading", worker_id=handle.worker_id)
            ready = adapter.wait_ready(handle, runtime, runtime.ready_timeout_seconds,
                                       cancelled=lambda: self.closed)
            if not ready:
                self._cleanup_runtime(operation_id, model_id, handle, runtime, "WORKER_READY_TIMEOUT",
                                      f"{runtime.name} did not finish loading within "
                                      f"{int(runtime.ready_timeout_seconds // 60)} minutes.")
                return
            self.store.update_operation(operation_id, status="ready", worker_id=handle.worker_id)
        except WorkerFailed as exc:
            self._cleanup_runtime(operation_id, model_id, handle, runtime, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - any adapter failure ends this load with cleanup.
            if handle is None:
                self.store.update_operation(operation_id, status="failed", error_code="WORKER_START_FAILED",
                                            error_message=f"{runtime.name} could not be started: {exc}")
                return
            self._cleanup_runtime(operation_id, model_id, handle, runtime, "WORKER_FAILED",
                                  f"{runtime.name} failed while starting: {exc}")

    def _cleanup_runtime(self, operation_id, model_id, handle, runtime, code, message):
        if handle is None:
            self.store.update_operation(operation_id, status="failed", error_code=code, error_message=message)
            return
        try:
            self.runtime_adapter.stop(handle)
            exited = self.runtime_adapter.wait_exited(handle, runtime.stop_timeout_seconds)
        except Exception:  # noqa: BLE001 - failed stop/wait means cleanup is not proven.
            exited = False
        if exited:
            with self.lock:
                self.runtime_handles.pop(model_id, None)
            self.store.update_operation(operation_id, status="failed", error_code=code, error_message=message)
        else:
            self.store.update_operation(operation_id, status="cleanup_failed", worker_id=handle.worker_id,
                                        error_code="WORKER_CLEANUP_FAILED",
                                        error_message=f"{message} The process did not exit; capacity stays reserved.")

    def _run_runtime_unload(self, operation_id, model_id, handle):
        runtime = self.catalog.runtimes.get(model_id)
        timeout = runtime.stop_timeout_seconds if runtime else self.settings.worker_stop_timeout_seconds
        try:
            self.runtime_adapter.stop(handle)
            exited = self.runtime_adapter.wait_exited(handle, timeout)
        except Exception:  # noqa: BLE001 - failed stop/wait means cleanup is not proven.
            exited = False
        if not exited:
            self.store.update_operation(operation_id, status="cleanup_failed", worker_id=handle.worker_id,
                                        error_code="WORKER_STOP_FAILED",
                                        error_message="The runtime process has not exited; capacity remains reserved.")
            return
        with self.lock:
            self.runtime_handles.pop(model_id, None)
        self.store.update_operation(operation_id, status="unloaded", worker_id=handle.worker_id)

    # ----- simulation profiles ---------------------------------------------------------

    def host_snapshot(self, host):
        result = dict(host)
        identity = result.get("host", {})
        basic_ok = identity.get("role") == "desktop" and identity.get("scope") == "host"
        gpus = result.get("gpus")
        telemetry_ok = (result.get("stale") is False and result.get("ram") is not None
                        and result.get("ram_error") is None and result.get("gpu_error") is None
                        and isinstance(gpus, list) and bool(gpus)
                        and all(isinstance(gpu, dict) and gpu.get("error") is None
                                and gpu.get("memory") is not None for gpu in gpus))
        result["loading_enabled"] = bool(basic_ok and telemetry_ok)
        result["loading_reason"] = (
            ("Configured runtimes and simulation profiles can be loaded."
             if self.catalog.runtimes else
             "Simulation loads are available; no inference is run by the fake worker.")
            if result["loading_enabled"] else
            "Loading requires a native desktop host with fresh RAM and complete per-GPU measurements."
        )
        return result

    def create_load(self, model_id, profile_id, idempotency_key, host):
        fingerprint = request_fingerprint("load", model_id, profile_id)
        with self.lock:
            self._ensure_open()
            result = self.store.create_load_operation(
                model_id=model_id, profile_id=profile_id, idempotency_key=idempotency_key,
                fingerprint=fingerprint, host=host,
                ram_headroom_bytes=self.settings.ram_headroom_bytes,
                gpu_headroom_bytes=self.settings.gpu_headroom_bytes,
            )
            if result.get("idempotency_conflict"):
                raise IdempotencyConflict("The idempotency key was already used for a different request.")
            if result.get("missing_model"):
                raise LifecycleError("MODEL_NOT_FOUND", "The model does not exist.", 404)
            operation = result.get("operation")
            if operation is None:
                raise LifecycleError("MODEL_NOT_FOUND", "The model does not exist.", 404)
            if operation["status"] == "refused":
                refusal = operation["refusal"] or {}
                raise LifecycleError(refusal.get("code", "LOAD_REFUSED"), refusal.get("message", "Load refused."),
                                     resources=refusal.get("resources", []),
                                     status_code=409, operation_id=operation["id"])
            if not result.get("existing"):
                try:
                    self.executor.submit(self._run_load, operation["id"], model_id)
                except RuntimeError:
                    self.store.update_operation(
                        operation["id"], status="failed", error_code="WORKER_START_FAILED",
                        error_message="The fake worker could not be scheduled.",
                    )
                    raise LifecycleError("WORKER_START_FAILED", "The fake worker could not be scheduled.", 503)
            return serialize_operation(operation)

    def _run_load(self, operation_id, model_id):
        handle = None
        with self.lock:
            if self.closed:
                self.store.update_operation(operation_id, status="failed", error_code="SERVICE_STOPPING",
                                            error_message="The service stopped before the fake worker started.")
                return
        try:
            profile = self.store.get_profile(model_id)
            if not profile:
                raise RuntimeError("Simulation profile disappeared before worker start.")
            handle = self.worker.spawn(model_id, profile)
            with self.lock:
                self.handles[model_id] = handle
            ready = self.worker.wait_ready(handle, self.settings.worker_ready_timeout_seconds)
            if not ready:
                self._cleanup_failed_load(operation_id, model_id, handle, "WORKER_READY_TIMEOUT",
                                          "The fake worker did not report ready before the timeout.")
                return
            self.store.update_operation(operation_id, status="simulation_ready", worker_id=handle.worker_id)
        except Exception:  # noqa: BLE001 - adapter and persistence failures terminate this fake load.
            if handle is None:
                try:
                    self.store.update_operation(operation_id, status="failed", error_code="WORKER_START_FAILED",
                                                error_message="The fake worker failed before it could start.")
                except Exception:  # noqa: BLE001 - retain the reservation if the DB is unavailable.
                    self.persistence_errors += 1
                return
            self._cleanup_failed_load(operation_id, model_id, handle, "WORKER_FAILED",
                                      "The fake worker failed while starting or becoming ready.")

    def _cleanup_failed_load(self, operation_id, model_id, handle, code, message):
        try:
            self.worker.stop(handle)
            exited = self.worker.wait_exited(handle, self.settings.worker_stop_timeout_seconds)
        except Exception:  # noqa: BLE001 - failed stop/wait means cleanup is not proven.
            exited = False
        if exited:
            with self.lock:
                self.handles.pop(model_id, None)
            self.store.update_operation(operation_id, status="failed", error_code=code, error_message=message)
        else:
            self.store.update_operation(operation_id, status="cleanup_failed", worker_id=handle.worker_id,
                                        error_code="WORKER_CLEANUP_FAILED",
                                        error_message="Worker cleanup did not finish; capacity remains reserved.")

    def create_unload(self, model_id, idempotency_key):
        fingerprint = request_fingerprint("unload", model_id)
        with self.lock:
            self._ensure_open()
            result = self.store.begin_unload(model_id=model_id, idempotency_key=idempotency_key,
                                             fingerprint=fingerprint)
            if result.get("idempotency_conflict"):
                raise IdempotencyConflict("The idempotency key was already used for a different request.")
            if result.get("missing_model"):
                raise LifecycleError("MODEL_NOT_FOUND", "The model does not exist.", 404)
            if result.get("busy"):
                raise LifecycleError("MODEL_BUSY", "Only a ready or cleanup-failed worker can be unloaded.")
            operation = result["operation"]
            if not result.get("existing"):
                try:
                    runtime_handle = self.runtime_handles.get(model_id)
                    if runtime_handle is not None and self.runtime_adapter is not None:
                        # Not on the runtime queue: a stop must not wait behind a long load.
                        threading.Thread(target=self._run_runtime_unload, name="runtime-stop", daemon=True,
                                         args=(operation["id"], model_id, runtime_handle)).start()
                    else:
                        self.executor.submit(self._run_unload, operation["id"], model_id)
                except RuntimeError:
                    self.store.update_operation(operation["id"], status="cleanup_failed",
                                                error_code="WORKER_STOP_FAILED",
                                                error_message="Unload could not be scheduled; reservation remains active.")
                    raise LifecycleError("WORKER_STOP_FAILED", "Unload could not be scheduled.", 503)
            return serialize_operation(operation)

    def _run_unload(self, operation_id, model_id):
        with self.lock:
            handle = self.handles.get(model_id)
        if handle is None:
            self.store.update_operation(operation_id, status="cleanup_failed", error_code="WORKER_HANDLE_MISSING",
                                        error_message="The owned fake worker handle is unavailable; reservation remains active.")
            return
        try:
            self.worker.stop(handle)
            exited = self.worker.wait_exited(handle, self.settings.worker_stop_timeout_seconds)
        except Exception:  # noqa: BLE001 - failed stop/wait means cleanup is not proven.
            exited = False
        if not exited:
            self.store.update_operation(operation_id, status="cleanup_failed", worker_id=handle.worker_id,
                                        error_code="WORKER_STOP_FAILED",
                                        error_message="The owned fake worker has not exited; capacity remains reserved.")
            return
        with self.lock:
            self.handles.pop(model_id, None)
        self.store.update_operation(operation_id, status="unloaded", worker_id=handle.worker_id)

    def operation(self, operation_id):
        operation = self.store.get_operation(operation_id)
        if not operation:
            raise LifecycleError("OPERATION_NOT_FOUND", "The operation does not exist.", 404)
        return serialize_operation(operation)

    def list_operations(self, limit=100):
        return {"operations": [serialize_operation(op) for op in self.store.list_operations(limit)]}

    def _ensure_open(self):
        if self.closed:
            raise LifecycleError("SERVICE_STOPPING", "The service is shutting down.", 503)

    def shutdown(self):
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=False)
        # A load in progress sees `closed`, stops its process, and records the failure.
        # Ready runtimes keep running and are re-adopted after the next start.
        self.runtime_executor.shutdown(wait=True, cancel_futures=False)
        # No operating-system process was spawned by this milestone. Any handles
        # left here disappear with this service; restart reconciliation marks rows.
