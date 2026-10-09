import asyncio
import json

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from generationstation.app import create_app
from generationstation.config import Settings

TOKEN = "t" * 48


class FakeStore:
    def __init__(self):
        self.closed = False

    def initialize(self):
        return "station-instance"

    def list_models(self):
        return [{"id": "image-model", "name": "Example", "workload": "image"}]

    def close(self):
        self.closed = True


class FakeMonitor:
    def __init__(self, snapshot=None):
        self.data = snapshot or {"ram": None, "ram_error": "unknown", "gpus": [],
                                 "gpu_error": "unknown", "stale": True,
                                 "loading_enabled": False}
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return self.data


def settings(**overrides):
    values = {"database_url": "postgresql+psycopg://test:test@localhost/test",
              "api_token": TOKEN}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_api_requires_bearer_token_and_does_not_leak_secrets():
    store, monitor = FakeStore(), FakeMonitor()
    app = create_app(settings=settings(), store=store, monitor=monitor)
    with TestClient(app) as client:
        assert client.get("/api/host").status_code == 401
        assert client.get("/api/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/api/host", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json()["instance_id"] == "station-instance"
    assert TOKEN not in response.text
    assert "test:test" not in response.text
    assert store.closed and monitor.started and monitor.stopped


def test_database_errors_return_generic_response_without_connection_details():
    class BrokenStore(FakeStore):
        def list_models(self):
            raise OperationalError("select", {}, Exception("postgresql://secret:password@db/prod"))

    app = create_app(settings=settings(), store=BrokenStore(), monitor=FakeMonitor())
    with TestClient(app) as client:
        response = client.get("/api/models", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert "password" not in response.text
    assert "secret" not in response.text
    assert response.json()["detail"] == "Database unavailable. Try again shortly."


def test_unknown_api_routes_do_not_fall_through_to_frontend():
    app = create_app(settings=settings(), store=FakeStore(), monitor=FakeMonitor())
    with TestClient(app) as client:
        assert client.get("/api/missing").status_code == 401
        response = client.get("/api/missing", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 404
    assert response.json() == {"detail": "API route not found"}


def test_database_failure_handler_does_not_affect_public_health_route():
    app = create_app(settings=settings(), store=FakeStore(), monitor=FakeMonitor())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.json() == {"status": "ok"}


def test_startup_failure_still_closes_store():
    class FailingMonitor(FakeMonitor):
        def start(self):
            raise RuntimeError("monitor failed")

    store = FakeStore()
    app = create_app(settings=settings(), store=store, monitor=FailingMonitor())
    try:
        with TestClient(app):
            pass
    except RuntimeError as exc:
        assert "monitor failed" in str(exc)
    else:
        raise AssertionError("monitor startup failure should propagate")
    assert store.closed


def test_events_requires_auth_and_emits_host_frames_with_no_store():
    monitor = FakeMonitor({"ram": None, "ram_error": "unknown", "gpus": [],
                           "gpu_error": "unknown", "stale": True})
    app = create_app(settings=settings(), store=FakeStore(), monitor=monitor)
    with TestClient(app) as client:
        assert client.get("/api/events").status_code == 401

    included_api_router = next(route.original_router for route in app.routes
                               if getattr(route, "original_router", None) is not None)
    route = next(route for route in included_api_router.routes if route.path == "/api/events")

    class RequestOnce:
        def __init__(self):
            self.checks = 0

        async def is_disconnected(self):
            self.checks += 1
            return False

    async def first_frame():
        response = await route.endpoint(RequestOnce())
        frame = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return response, frame

    response, frame = asyncio.run(first_frame())
    assert response.media_type == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert frame.startswith("event: host\ndata: ")
    assert json.loads(frame.split("data: ", 1)[1])["instance_id"] == "station-instance"


def test_cors_refuses_untrusted_origin_and_allows_configured_origin():
    app = create_app(settings=settings(allowed_origins=["https://station.example"]),
                     store=FakeStore(), monitor=FakeMonitor())
    with TestClient(app) as client:
        untrusted = client.options("/api/host", headers={
            "Origin": "https://attacker.example", "Access-Control-Request-Method": "GET",
        })
        trusted = client.options("/api/host", headers={
            "Origin": "https://station.example", "Access-Control-Request-Method": "GET",
        })
    assert "access-control-allow-origin" not in untrusted.headers
    assert trusted.headers["access-control-allow-origin"] == "https://station.example"
