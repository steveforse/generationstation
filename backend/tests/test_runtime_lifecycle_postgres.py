"""Real-runtime lifecycle against PostgreSQL, with a fake Basalt process (no model is loaded)."""
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from generationstation.config import Settings
from generationstation.lifecycle import LifecycleError, LifecycleManager
from generationstation.process_worker import ProcessSupervisor
from generationstation.storage import Store, reservations
from tests.runtime_fixtures import catalog, free_port, host

BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.database


@contextmanager
def migrated_store():
    database_url = os.environ.get("GS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set GS_TEST_DATABASE_URL to run disposable PostgreSQL integration checks")
    parsed = make_url(database_url)
    schema = "gs_test_" + uuid.uuid4().hex
    admin = create_engine(database_url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            config = Config(str(BACKEND / "alembic.ini"))
            config.attributes["connection"] = connection
            config.attributes["database_url"] = url.render_as_string(hide_password=False)
            command.upgrade(config, "head")
        store = Store(url.render_as_string(hide_password=False))
        store.initialize()
        try:
            yield store
        finally:
            store.close()
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def settings():
    return Settings(_env_file=None, database_url="postgresql+psycopg://t:t@localhost/t",
                    api_token="x" * 40, host_role="desktop", runtimes_file=None,
                    ram_headroom_bytes=0, gpu_headroom_bytes=0)


def wait_for(lifecycle, operation_id, statuses, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        operation = lifecycle.operation(operation_id)
        if operation["status"] in statuses:
            return operation
        time.sleep(0.1)
    raise AssertionError(f"operation stayed {operation['status']}")


def manager(store, tmp_path, port, **catalog_args):
    lifecycle = LifecycleManager(store, settings(), catalog=catalog(port, **catalog_args),
                                 runtime_adapter=ProcessSupervisor(tmp_path, poll_seconds=0.1))
    lifecycle.sync_catalog()
    return lifecycle


def active_reservations(store):
    with store.engine.connect() as conn:
        return conn.execute(select(reservations).where(reservations.c.active.is_(True))).all()


def test_start_ready_stop_and_capacity(tmp_path):
    port = free_port()
    with migrated_store() as store:
        lifecycle = manager(store, tmp_path, port, env={"FAKE_BASALT_DELAY": "0.5"})
        try:
            assert [m["id"] for m in store.list_models()] == ["basalt"]
            # Not enough free VRAM on the 4080 for the DeepSeek estimate: refused, no process.
            with pytest.raises(LifecycleError) as refused:
                lifecycle.create_runtime_load("basalt", "ds41", {}, None, "key-refuse-1", host((30, 4)))
            assert refused.value.code == "INSUFFICIENT_VRAM"
            assert refused.value.resources[0]["resource"] == "gpu:GPU-1"
            with pytest.raises(LifecycleError) as invalid:
                lifecycle.create_runtime_load("basalt", "ds41", {"vram_reserve_mib": 1}, None, "key-bad-1",
                                              host())
            assert invalid.value.code == "SETTINGS_INVALID"

            started = lifecycle.create_runtime_load("basalt", "ds41", {"ram_reserve_mib": 2048}, None,
                                                    "key-start-1", host())
            assert started["status"] == "loading" and started["simulation"] is False
            assert started["launch"]["settings"]["ram_reserve_mib"] == 2048
            # Same key and same request returns the same operation.
            again = lifecycle.create_runtime_load("basalt", "ds41", {"ram_reserve_mib": 2048}, None,
                                                  "key-start-1", host())
            assert again["id"] == started["id"]
            ready = wait_for(lifecycle, started["id"], {"ready", "failed"})
            assert ready["status"] == "ready", ready
            # Memory is now visible in telemetry, so the reservation is released.
            assert active_reservations(store) == []
            assert lifecycle.runtime_catalog(host())[0]["last_launch"]["settings"]["ram_reserve_mib"] == 2048
            with pytest.raises(LifecycleError) as busy:
                lifecycle.create_runtime_load("basalt", "fn", {}, None, "key-busy-1", host())
            assert busy.value.code == "MODEL_BUSY"

            unload = lifecycle.create_unload("basalt", "key-stop-1")
            done = wait_for(lifecycle, unload["id"], {"unloaded", "cleanup_failed"})
            assert done["status"] == "unloaded"
            assert store.list_models()[0]["state"] == "unloaded"
        finally:
            lifecycle.shutdown()


def test_early_exit_is_recorded_with_basalt_message(tmp_path):
    port = free_port()
    with migrated_store() as store:
        lifecycle = manager(store, tmp_path, port, env={"FAKE_BASALT_MODE": "exit"})
        try:
            started = lifecycle.create_runtime_load("basalt", None, {}, None, "key-exit-1", host())
            failed = wait_for(lifecycle, started["id"], {"failed", "ready"})
            assert failed["status"] == "failed" and failed["error_code"] == "WORKER_EXITED"
            assert "resident-budget-gib 40" in failed["error_message"]
            assert store.list_models()[0]["state"] == "error"
            assert active_reservations(store) == []
        finally:
            lifecycle.shutdown()


def test_external_server_on_the_port_is_refused(tmp_path):
    import socket
    port = free_port()
    listener = socket.socket()
    listener.bind(("127.0.0.1", port))
    listener.listen()
    try:
        with migrated_store() as store:
            lifecycle = manager(store, tmp_path, port)
            try:
                with pytest.raises(LifecycleError) as refused:
                    lifecycle.create_runtime_load("basalt", None, {}, None, "key-port-1", host())
                assert refused.value.code == "PORT_IN_USE"
            finally:
                lifecycle.shutdown()
    finally:
        listener.close()


def test_restart_readopts_a_ready_runtime_and_detects_a_crash(tmp_path):
    port = free_port()
    with migrated_store() as store:
        first = manager(store, tmp_path, port, env={"FAKE_BASALT_DELAY": "0.2"})
        started = first.create_runtime_load("basalt", None, {}, None, "key-adopt-1", host())
        assert wait_for(first, started["id"], {"ready", "failed"})["status"] == "ready"
        handle = first.runtime_handles["basalt"]
        first.shutdown()  # the ready process keeps running across a service restart

        second = manager(store, tmp_path, port)
        try:
            keep = second.recover_runtime_processes()
            store.reconcile_restart(keep)
            assert keep == [started["id"]]
            assert store.list_models()[0]["state"] == "ready"
            # Simulate a crash: the process dies outside Generation Station.
            second.runtime_adapter.stop(handle)
            second.runtime_adapter.wait_exited(handle, 10)
            second.refresh_runtime_health()
            model = store.list_models()[0]
            assert model["state"] == "error"
            assert second.operation(started["id"])["error_code"] == "WORKER_EXITED"
        finally:
            second.shutdown()
