import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from generationstation.app import create_app
from generationstation.config import Settings
from generationstation.lifecycle import FakeWorkerAdapter, LifecycleError
from tests.m2_fakes import MemoryStore, SnapshotMonitor, make_host

TOKEN = "m" * 48
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_settings(**overrides):
    values = {
        "database_url": "postgresql+psycopg://test:test@localhost/test",
        "api_token": TOKEN, "host_role": "desktop", "host_label": "test desktop",
        "ram_headroom_bytes": 0, "gpu_headroom_bytes": 0,
        "worker_ready_timeout_seconds": 1, "worker_stop_timeout_seconds": 1,
        "runtimes_file": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def profile_payload(model_id="model-one", *, ram=100, gpu=None):
    return {"id": model_id, "name": model_id, "workload": "image",
            "ram_peak_bytes": ram, "gpu_vram_bytes_by_id": gpu or {}, "mode": "simulation"}


def create_profile(client, model_id="model-one", *, ram=100, gpu=None):
    response = client.post("/api/profiles", headers=AUTH,
                           json=profile_payload(model_id, ram=ram, gpu=gpu))
    assert response.status_code == 201, response.text
    return response.json()["profile"]


def wait_for_status(client, operation_id, status, timeout=2):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/operations/{operation_id}", headers=AUTH)
        assert response.status_code == 200
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.01)
    raise AssertionError(f"Operation never reached {status}: {last}")


class ControlledWorker(FakeWorkerAdapter):
    def __init__(self, *, ready=True, exits=True, fail_spawn=False):
        super().__init__()
        self.ready_result = ready
        self.exit_results = [exits]
        self.fail_spawn = fail_spawn
        self.exit_calls = 0

    def spawn(self, model_id, profile):
        if self.fail_spawn:
            raise RuntimeError("injected spawn failure")
        return super().spawn(model_id, profile)

    def wait_ready(self, handle, timeout_seconds):
        return self.ready_result

    def wait_exited(self, handle, timeout_seconds):
        self.exit_calls += 1
        result = self.exit_results.pop(0) if self.exit_results else True
        if result:
            handle.exited = True
        return result


def app_parts(host=None, *, store=None, worker=None, **settings_overrides):
    store = store or MemoryStore()
    monitor = SnapshotMonitor(host or make_host())
    app = create_app(settings=make_settings(**settings_overrides), store=store,
                     monitor=monitor, worker=worker or ControlledWorker())
    return app, store, monitor, app.state.lifecycle


def load(client, model_id, profile, key="load-key-0001"):
    return client.post(f"/api/models/{model_id}/load", headers={**AUTH, "Idempotency-Key": key},
                       json={"profile_id": profile["id"]})


def unload(client, model_id, key="unload-key-0001"):
    return client.post(f"/api/models/{model_id}/unload", headers={**AUTH, "Idempotency-Key": key})


def test_profiles_create_model_identity_and_cannot_change_while_loaded():
    app, _, _, _ = app_parts()
    with TestClient(app) as client:
        profile = create_profile(client)
        assert profile["id"] != profile["model_id"]
        assert profile["mode"] == "simulation"
        assert profile["revision"] == 1
        assert client.get("/api/models", headers=AUTH).json()["models"][0]["profile"]["id"] == profile["id"]
        accepted = load(client, "model-one", profile)
        assert accepted.status_code == 202
        ready = wait_for_status(client, accepted.json()["id"], "simulation_ready")
        assert ready["simulation"] is True and ready["worker_type"] == "fake"
        changed = client.put("/api/profiles/model-one", headers=AUTH,
                             json={**profile_payload(ram=200), "id": "extra"})
        assert changed.status_code == 422
        changed = client.put("/api/profiles/model-one", headers=AUTH,
                             json={k: v for k, v in profile_payload(ram=200).items() if k != "id"})
        assert changed.status_code == 409
        deleted = client.delete("/api/profiles/model-one", headers=AUTH)
        assert deleted.status_code == 409


def test_profile_revision_increments_when_updated_after_unload():
    app, _, _, _ = app_parts()
    with TestClient(app) as client:
        profile = create_profile(client)
        updated = client.put("/api/profiles/model-one", headers=AUTH,
                             json={"name": "updated", "workload": "video", "ram_peak_bytes": 200,
                                   "gpu_vram_bytes_by_id": {"GPU-A": 100}, "mode": "simulation"})
        assert updated.status_code == 200
        assert updated.json()["profile"]["revision"] == profile["revision"] + 1
        assert client.get("/api/profiles", headers=AUTH).json()["profiles"][0]["name"] == "updated"


def test_deleted_profile_can_be_recreated_without_losing_operation_history():
    app, _, _, _ = app_parts()
    with TestClient(app) as client:
        original = create_profile(client)
        accepted = load(client, "model-one", original)
        wait_for_status(client, accepted.json()["id"], "simulation_ready")
        stopped = unload(client, "model-one")
        wait_for_status(client, stopped.json()["id"], "unloaded")
        assert client.delete("/api/profiles/model-one", headers=AUTH).status_code == 200
        replacement = create_profile(client, "model-one", ram=200)
        assert replacement["id"] != original["id"]
        operation = client.get(f"/api/operations/{accepted.json()['id']}", headers=AUTH).json()
        assert operation["status"] == "simulation_ready"
        assert client.get("/api/models", headers=AUTH).json()["models"][0]["id"] == "model-one"


def test_load_endpoint_enforces_direct_admission_and_returns_shortage_details():
    app, store, _, _ = app_parts(make_host(role="development", ram_available=1000))
    with TestClient(app) as client:
        profile = create_profile(client, ram=1001)
        denied = load(client, "model-one", profile)
        assert denied.status_code == 409
        refusal = denied.json()["detail"]
        assert refusal["code"] == "HOST_ROLE_UNSUPPORTED"
        assert refusal["operation_id"]
        operation = client.get(f"/api/operations/{refusal['operation_id']}", headers=AUTH).json()
        assert operation["status"] == "refused"
        assert operation["simulation"] is True
        assert store.reservations == {}


@pytest.mark.parametrize(("host", "code"), [
    (make_host(stale=True), "TELEMETRY_STALE"),
    (make_host(age=5), "TELEMETRY_STALE"),
    (make_host(ram_unknown=True), "TELEMETRY_UNKNOWN"),
    (make_host(gpu_error="NVML unavailable"), "GPU_ACCOUNTING_UNSUPPORTED"),
    (make_host(gpu_failures=("GPU-A",)), "GPU_ACCOUNTING_UNSUPPORTED"),
])
def test_load_refuses_stale_unknown_and_incomplete_capacity(host, code):
    app, store, _, _ = app_parts(host)
    with TestClient(app) as client:
        profile = create_profile(client)
        response = load(client, "model-one", profile)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == code
        assert store.reservations == {}


def test_load_checks_exact_gpu_device_and_gpu_capacity_cannot_be_summed():
    app, _, _, _ = app_parts(make_host(gpu_available={"GPU-A": 50, "GPU-B": 50}))
    worker = app.state.lifecycle.worker
    with TestClient(app) as client:
        profile = create_profile(client, gpu={"GPU-A": 90})
        response = load(client, "model-one", profile)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "INSUFFICIENT_VRAM"
        assert detail["resources"] == [{"resource": "gpu:GPU-A", "required_bytes": 90,
                                         "available_bytes": 50, "headroom_bytes": 0}]
        assert worker.spawned == []


def test_load_idempotency_returns_same_operation_and_rejects_key_reuse():
    app, _, _, _ = app_parts()
    worker = app.state.lifecycle.worker
    with TestClient(app) as client:
        profile = create_profile(client)
        first = load(client, "model-one", profile, "stable-key-001")
        second = load(client, "model-one", profile, "stable-key-001")
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]
        wait_for_status(client, first.json()["id"], "simulation_ready")
        assert len(worker.spawned) == 1
        other = create_profile(client, "model-two")
        reused = load(client, "model-two", other, "stable-key-001")
        assert reused.status_code == 409
        assert reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_concurrent_loads_for_different_models_cannot_over_admit():
    host = make_host(ram_available=1000, gpu_available={"GPU-A": 1000})
    app, store, _, _ = app_parts(host, ram_headroom_bytes=0)
    with TestClient(app) as client:
        first = create_profile(client, "model-one", ram=600)
        second = create_profile(client, "model-two", ram=600)
        manager = app.state.lifecycle

        def attempt(model_id, profile, key):
            try:
                return manager.create_load(model_id, profile["id"], key, manager.host_snapshot(host))
            except LifecycleError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda args: attempt(*args), [
                ("model-one", first, "concurrent-key-1"),
                ("model-two", second, "concurrent-key-2"),
            ]))
        accepted = [outcome for outcome in outcomes if isinstance(outcome, dict)]
        refused = [outcome for outcome in outcomes if isinstance(outcome, LifecycleError)]
        assert len(accepted) == len(refused) == 1
        assert refused[0].code == "INSUFFICIENT_RAM"
        assert len([r for r in store.reservations.values() if r["active"]]) == 1


def test_ready_timeout_cleans_fake_worker_and_releases_reservation():
    worker = ControlledWorker(ready=False, exits=True)
    app, store, _, _ = app_parts(worker=worker)
    with TestClient(app) as client:
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        assert accepted.status_code == 202
        failed = wait_for_status(client, accepted.json()["id"], "failed")
        assert failed["error_code"] == "WORKER_READY_TIMEOUT"
        assert worker.stopped == [worker.spawned[0][1].worker_id]
        assert not any(res["active"] for res in store.reservations.values())


def test_readiness_cleanup_failure_keeps_capacity_reserved_until_later_unload():
    worker = ControlledWorker(ready=False, exits=False)
    app, store, _, _ = app_parts(worker=worker)
    with TestClient(app) as client:
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        stuck = wait_for_status(client, accepted.json()["id"], "cleanup_failed")
        assert stuck["error_code"] == "WORKER_CLEANUP_FAILED"
        assert any(res["active"] for res in store.reservations.values())
        worker.exit_results.append(True)
        stopping = unload(client, "model-one", "cleanup-retry-key")
        assert stopping.status_code == 202
        wait_for_status(client, stopping.json()["id"], "unloaded")
        assert not any(res["active"] for res in store.reservations.values())


def test_spawn_failure_releases_reservation_and_is_persisted():
    worker = ControlledWorker(fail_spawn=True)
    app, store, _, _ = app_parts(worker=worker)
    with TestClient(app) as client:
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        failed = wait_for_status(client, accepted.json()["id"], "failed")
        assert failed["error_code"] == "WORKER_START_FAILED"
        assert not any(res["active"] for res in store.reservations.values())


def test_profile_lookup_failure_before_spawn_releases_reservation_when_store_recovers():
    class FlakyStore(MemoryStore):
        fail_profile_once = True

        def get_profile(self, model_id):
            if self.fail_profile_once:
                self.fail_profile_once = False
                raise RuntimeError("injected database read failure")
            return super().get_profile(model_id)

    store = FlakyStore()
    worker = ControlledWorker()
    app, _, _, _ = app_parts(store=store, worker=worker)
    with TestClient(app) as client:
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        failed = wait_for_status(client, accepted.json()["id"], "failed")
        assert failed["error_code"] == "WORKER_START_FAILED"
        assert worker.spawned == []
        assert not any(res["active"] for res in store.reservations.values())


def test_unload_works_when_telemetry_has_become_stale_and_releases_only_after_exit():
    worker = ControlledWorker(exits=False)
    app, store, monitor, _ = app_parts(worker=worker)
    with TestClient(app) as client:
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        wait_for_status(client, accepted.json()["id"], "simulation_ready")
        monitor.data["stale"] = True
        stopping = unload(client, "model-one")
        assert stopping.status_code == 202
        cleanup = wait_for_status(client, stopping.json()["id"], "cleanup_failed")
        assert cleanup["error_code"] == "WORKER_STOP_FAILED"
        assert any(res["active"] for res in store.reservations.values())
        worker.exit_results.append(True)
        retry = unload(client, "model-one", "unload-key-retry")
        assert retry.status_code == 202
        wait_for_status(client, retry.json()["id"], "unloaded")
        assert not any(res["active"] for res in store.reservations.values())


def test_restart_reconciliation_does_not_trust_or_terminate_persisted_worker_ids():
    store = MemoryStore()
    old_worker = ControlledWorker()
    app, _, _, _ = app_parts(store=store, worker=old_worker)
    with TestClient(app) as client:
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        wait_for_status(client, accepted.json()["id"], "simulation_ready")
        operation_id = accepted.json()["id"]
    assert store.operations[operation_id]["status"] == "simulation_ready"
    assert any(res["active"] for res in store.reservations.values())

    restarted_app, _, _, _ = app_parts(store=store, worker=ControlledWorker())
    with TestClient(restarted_app) as client:
        recovered = client.get(f"/api/operations/{operation_id}", headers=AUTH).json()
        assert recovered["status"] == "failed"
        assert recovered["error_code"] == "SERVICE_RESTART"
        assert not any(res["active"] for res in store.reservations.values())
        assert unload(client, "model-one", "unload-after-restart").status_code == 409
    assert old_worker.stopped == []


def test_unknown_model_returns_404_and_operation_history_survives_terminal_states():
    app, _, _, _ = app_parts()
    with TestClient(app) as client:
        missing = client.post("/api/models/not-created/load", headers={**AUTH, "Idempotency-Key": "missing-key-01"},
                              json={"profile_id": "profile-does-not-exist"})
        assert missing.status_code == 404
        profile = create_profile(client)
        accepted = load(client, "model-one", profile)
        wait_for_status(client, accepted.json()["id"], "simulation_ready")
        history = client.get("/api/operations", headers=AUTH)
        assert history.status_code == 200
        assert any(item["id"] == accepted.json()["id"] for item in history.json()["operations"])
