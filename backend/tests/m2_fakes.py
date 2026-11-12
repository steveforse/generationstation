import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from generationstation.admission import evaluate_capacity


def make_host(*, role="desktop", scope="host", ram_available=10_000, gpu_available=None,
              stale=False, age=0.1, ram_unknown=False, gpu_error=None, gpu_failures=()):
    gpu_available = gpu_available or {"GPU-A": 10_000, "GPU-B": 10_000}
    return {
        "host": {"hostname": "test-host", "os": "Windows", "label": "test desktop",
                 "role": role, "scope": scope},
        "ram": None if ram_unknown else {
            "total_bytes": 20_000, "available_bytes": ram_available,
            "used_bytes": 20_000 - ram_available,
        },
        "ram_error": "unknown" if ram_unknown else None,
        "gpus": [{"id": device_id, "name": device_id,
                  "memory": None if device_id in gpu_failures else {
                      "total_bytes": 20_000, "available_bytes": available,
                      "used_bytes": 20_000 - available,
                  },
                  "error": "unsupported" if device_id in gpu_failures else None}
                 for device_id, available in gpu_available.items()],
        "gpu_error": gpu_error,
        "stale": stale, "age_seconds": age, "stale_after_seconds": 5,
        "sequence": 1, "status": "stale" if stale else "live",
    }


class MemoryStore:
    """Injected thread-safe persistence fake. No SQL dialect or SQLite involved."""

    def __init__(self):
        self.lock = threading.RLock()
        self.models = {}
        self.profiles = {}
        self.runtime = {}
        self.operations = {}
        self.idempotency = {}
        self.reservations = {}
        self.closed = False
        self.restarted = False

    def initialize(self):
        return "test-instance"

    def acquire_scheduler_lock(self):
        pass

    def release_scheduler_lock(self):
        pass

    def reconcile_restart(self, keep_operation_ids=()):
        with self.lock:
            active = {"loading", "simulation_ready", "ready", "unloading", "cleanup_failed"}
            for operation in self.operations.values():
                if operation["status"] in active and operation["id"] not in set(keep_operation_ids):
                    operation["status"] = "failed"
                    operation["error_code"] = "SERVICE_RESTART"
                    operation["error_message"] = "The fake worker was discarded during service restart."
                    operation["updated_at"] = datetime.now(timezone.utc)
                    runtime = self.runtime[operation["model_id"]]
                    runtime.update(state="error", active_operation_id=None,
                                   reservation_operation_id=None, active_worker_id=None,
                                   last_error_code="SERVICE_RESTART")
                    reservation_id = operation.get("reservation_operation_id") or operation["id"]
                    if reservation_id in self.reservations:
                        self.reservations[reservation_id]["active"] = False
            self.restarted = True

    def close(self):
        self.closed = True

    def list_models(self):
        with self.lock:
            result = []
            for model_id, model in self.models.items():
                profile = self.profiles.get(model_id)
                runtime = self.runtime[model_id]
                result.append({"id": model_id, "name": model["name"], "workload": model["workload"],
                               "state": runtime["state"], "loading_enabled": bool(profile) and runtime["state"] in {"unloaded", "error"},
                               "profile": {"id": profile["id"] if profile else None,
                                           "revision": profile["revision"] if profile else None}})
            return result

    def list_profiles(self):
        with self.lock:
            return [deepcopy(profile) for profile in self.profiles.values()]

    def create_profile(self, values):
        with self.lock:
            model_id = values["id"]
            self.models[model_id] = {"id": model_id, "name": values["name"], "workload": values["workload"]}
            profile = {"id": str(uuid.uuid4()), "model_id": model_id, "name": values["name"],
                       "workload": values["workload"], "ram_peak_bytes": values["ram_peak_bytes"],
                       "gpu_vram_bytes_by_id": dict(values["gpu_vram_bytes_by_id"]), "mode": "simulation",
                       "revision": 1}
            self.profiles[model_id] = profile
            self.runtime[model_id] = {"state": "unloaded", "active_operation_id": None,
                                      "reservation_operation_id": None, "active_worker_id": None}
            return deepcopy(profile)

    def get_profile(self, model_id):
        with self.lock:
            profile = self.profiles.get(model_id)
            return deepcopy(profile) if profile else None

    def update_profile(self, model_id, values):
        with self.lock:
            runtime = self.runtime.get(model_id)
            profile = self.profiles.get(model_id)
            if not runtime or not profile:
                return None
            if runtime["state"] not in {"unloaded", "error"}:
                return {"busy": True}
            self.models[model_id].update(name=values["name"], workload=values["workload"])
            profile.update(name=values["name"], workload=values["workload"],
                           ram_peak_bytes=values["ram_peak_bytes"],
                           gpu_vram_bytes_by_id=dict(values["gpu_vram_bytes_by_id"]),
                           revision=profile["revision"] + 1)
            return deepcopy(profile)

    def delete_profile(self, model_id):
        with self.lock:
            if model_id not in self.profiles:
                return "missing"
            if self.runtime[model_id]["state"] not in {"unloaded", "error"}:
                return "busy"
            del self.profiles[model_id]
            return "deleted"

    def get_operation(self, operation_id):
        with self.lock:
            op = self.operations.get(operation_id)
            return deepcopy(op) if op else None

    def list_operations(self, limit=100):
        with self.lock:
            rows = sorted(self.operations.values(), key=lambda op: op["created_at"], reverse=True)
            return deepcopy(rows[:limit])

    def active_reservations(self, conn=None):
        with self.lock:
            return [deepcopy(reservation) for reservation in self.reservations.values()
                    if reservation["active"]]

    def create_load_operation(self, *, model_id, profile_id, idempotency_key, fingerprint, host,
                              ram_headroom_bytes, gpu_headroom_bytes):
        with self.lock:
            existing_id = self.idempotency.get(idempotency_key)
            if existing_id:
                operation = deepcopy(self.operations[existing_id])
                if operation["request_fingerprint"] != fingerprint:
                    return {"idempotency_conflict": True, "operation": operation}
                return {"existing": True, "operation": operation}
            profile = self.profiles.get(model_id)
            if model_id not in self.models:
                return {"missing_model": True, "operation": None}
            if not profile or profile["id"] != profile_id:
                return self._refusal(model_id, profile_id if profile else None, idempotency_key,
                                     fingerprint, {"code": "PROFILE_NOT_FOUND",
                                     "message": "The model or simulation profile was not found.", "resources": []})
            runtime = self.runtime[model_id]
            if runtime["state"] not in {"unloaded", "error"}:
                return self._refusal(model_id, profile_id, idempotency_key, fingerprint,
                                     {"code": "MODEL_BUSY", "message": "This model already has an active worker operation.", "resources": []},
                                     profile["revision"])
            refusal = evaluate_capacity(host, profile, self.active_reservations(),
                                        ram_headroom_bytes, gpu_headroom_bytes)
            if refusal:
                return self._refusal(model_id, profile_id, idempotency_key, fingerprint,
                                     refusal, profile["revision"])
            now, operation_id = datetime.now(timezone.utc), str(uuid.uuid4())
            operation = {"id": operation_id, "model_id": model_id, "profile_id": profile_id,
                         "profile_revision": profile["revision"], "action": "load", "status": "loading",
                         "idempotency_key": idempotency_key, "request_fingerprint": fingerprint,
                         "parent_operation_id": None, "reservation_operation_id": operation_id,
                         "worker_id": None, "refusal": None, "error_code": None,
                         "error_message": None, "created_at": now, "updated_at": now}
            self.operations[operation_id] = operation
            self.idempotency[idempotency_key] = operation_id
            self.reservations[operation_id] = {"operation_id": operation_id, "model_id": model_id,
                                               "ram_bytes": profile["ram_peak_bytes"],
                                               "gpu_vram_bytes_by_id": dict(profile["gpu_vram_bytes_by_id"]),
                                               "active": True}
            runtime.update(state="loading", active_operation_id=operation_id,
                           reservation_operation_id=operation_id, active_worker_id=None)
            return {"operation": deepcopy(operation), "existing": False}

    def _refusal(self, model_id, profile_id, key, fingerprint, refusal, revision=None):
        now, operation_id = datetime.now(timezone.utc), str(uuid.uuid4())
        operation = {"id": operation_id, "model_id": model_id, "profile_id": profile_id,
                     "profile_revision": revision, "action": "load", "status": "refused",
                     "idempotency_key": key, "request_fingerprint": fingerprint,
                     "parent_operation_id": None, "reservation_operation_id": None,
                     "worker_id": None, "refusal": refusal, "error_code": None,
                     "error_message": None, "created_at": now, "updated_at": now}
        self.operations[operation_id] = operation
        self.idempotency[key] = operation_id
        return {"operation": deepcopy(operation), "existing": False}

    def begin_unload(self, *, model_id, idempotency_key, fingerprint):
        with self.lock:
            existing_id = self.idempotency.get(idempotency_key)
            if existing_id:
                operation = deepcopy(self.operations[existing_id])
                if operation["request_fingerprint"] != fingerprint:
                    return {"idempotency_conflict": True, "operation": operation}
                return {"existing": True, "operation": operation}
            runtime = self.runtime.get(model_id)
            if runtime is None:
                return {"missing_model": True}
            if runtime["state"] not in {"simulation_ready", "cleanup_failed"}:
                return {"busy": True, "state": runtime["state"]}
            parent_id = runtime["active_operation_id"]
            parent = self.operations[parent_id]
            now, operation_id = datetime.now(timezone.utc), str(uuid.uuid4())
            operation = {"id": operation_id, "model_id": model_id, "profile_id": parent["profile_id"],
                         "profile_revision": parent["profile_revision"], "action": "unload", "status": "unloading",
                         "idempotency_key": idempotency_key, "request_fingerprint": fingerprint,
                         "parent_operation_id": parent_id,
                         "reservation_operation_id": runtime["reservation_operation_id"],
                         "worker_id": runtime["active_worker_id"], "refusal": None, "error_code": None,
                         "error_message": None, "created_at": now, "updated_at": now}
            self.operations[operation_id] = operation
            self.idempotency[idempotency_key] = operation_id
            runtime.update(state="unloading", active_operation_id=operation_id)
            return {"operation": deepcopy(operation), "existing": False}

    def update_operation(self, operation_id, *, status, worker_id=None, error_code=None,
                         error_message=None, refusal=None):
        with self.lock:
            operation = self.operations[operation_id]
            operation.update(status=status, updated_at=datetime.now(timezone.utc))
            if worker_id is not None:
                operation["worker_id"] = worker_id
            if error_code is not None:
                operation["error_code"] = error_code
            if error_message is not None:
                operation["error_message"] = error_message
            if refusal is not None:
                operation["refusal"] = refusal
            runtime = self.runtime[operation["model_id"]]
            if status == "simulation_ready" or status == "cleanup_failed":
                runtime.update(state=status, active_operation_id=operation_id, active_worker_id=worker_id)
            elif status == "unloaded":
                runtime.update(state="unloaded", active_operation_id=None,
                               reservation_operation_id=None, active_worker_id=None)
            elif status == "failed":
                runtime.update(state="error", active_operation_id=None,
                               reservation_operation_id=None, active_worker_id=None)
            if status in {"failed", "unloaded"}:
                reservation_id = operation.get("reservation_operation_id") or operation["id"]
                if reservation_id in self.reservations:
                    self.reservations[reservation_id]["active"] = False
            return deepcopy(operation)


class SnapshotMonitor:
    def __init__(self, host):
        self.data = deepcopy(host)
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return deepcopy(self.data)
