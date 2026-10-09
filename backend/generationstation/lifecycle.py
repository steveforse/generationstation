"""Serialized capacity admission and process-local fake-worker lifecycle."""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256


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
    raw = json.dumps([action, model_id, profile_id], separators=(",", ":"), ensure_ascii=True)
    return sha256(raw.encode("ascii")).hexdigest()


def serialize_operation(operation):
    return {
        "id": operation["id"], "operation_id": operation["id"], "model_id": operation["model_id"],
        "profile_id": operation.get("profile_id"), "profile_revision": operation.get("profile_revision"),
        "action": operation["action"], "status": operation["status"],
        "simulation": True, "worker_type": "fake", "created_at": operation["created_at"].isoformat()
        if hasattr(operation.get("created_at"), "isoformat") else operation.get("created_at"),
        "updated_at": operation["updated_at"].isoformat()
        if hasattr(operation.get("updated_at"), "isoformat") else operation.get("updated_at"),
        "error_code": operation.get("error_code"), "error_message": operation.get("error_message"),
        "refusal": operation.get("refusal"),
    }


class LifecycleManager:
    def __init__(self, store, settings, worker=None):
        self.store = store
        self.settings = settings
        self.worker = worker or FakeWorkerAdapter()
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake-worker")
        self.handles = {}
        self.closed = False
        self.persistence_errors = 0

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
            "Simulation loads are available; no inference is run by the fake worker."
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
                raise LifecycleError("MODEL_BUSY", "Only a simulation-ready or cleanup-failed worker can be unloaded.")
            operation = result["operation"]
            if not result.get("existing"):
                try:
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
        # No operating-system process was spawned by this milestone. Any handles
        # left here disappear with this service; restart reconciliation marks rows.
