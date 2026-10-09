import asyncio
import json
import re
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .config import ROOT, Settings
from .lifecycle import IdempotencyConflict, LifecycleError, LifecycleManager
from .storage import Store
from .telemetry import Monitor


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1, max_length=64)
    name: StrictStr = Field(min_length=1, max_length=200)
    workload: StrictStr = Field(min_length=1, max_length=40)
    ram_peak_bytes: StrictInt = Field(gt=0, le=2**63 - 1)
    gpu_vram_bytes_by_id: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    mode: Literal["simulation"]

    @field_validator("id")
    @classmethod
    def model_id_format(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
            raise ValueError("Use letters, numbers, dot, underscore, and hyphen for the model ID.")
        return value

    @field_validator("name", "workload")
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError("Value cannot be blank.")
        return value.strip()

    @field_validator("gpu_vram_bytes_by_id")
    @classmethod
    def valid_gpu_requirements(cls, value):
        if len(value) > 16:
            raise ValueError("A profile may target at most 16 GPU devices.")
        if any(not device_id or len(device_id) > 160 or amount <= 0 or amount > 2**63 - 1
               for device_id, amount in value.items()):
            raise ValueError("GPU IDs and VRAM requirements must be valid and positive.")
        return value


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(min_length=1, max_length=200)
    workload: StrictStr = Field(min_length=1, max_length=40)
    ram_peak_bytes: StrictInt = Field(gt=0, le=2**63 - 1)
    gpu_vram_bytes_by_id: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    mode: Literal["simulation"]

    @field_validator("name", "workload")
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError("Value cannot be blank.")
        return value.strip()

    @field_validator("gpu_vram_bytes_by_id")
    @classmethod
    def valid_gpu_requirements(cls, value):
        if len(value) > 16 or any(not device_id or len(device_id) > 160 or amount <= 0 or amount > 2**63 - 1
                                  for device_id, amount in value.items()):
            raise ValueError("GPU IDs and VRAM requirements must be valid and positive.")
        return value


class LoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: StrictStr = Field(min_length=1, max_length=36)


def create_app(settings=None, store=None, monitor=None, worker=None):
    settings = settings or Settings()
    store = store if store is not None else Store(settings.database_url.get_secret_value())
    monitor = monitor if monitor is not None else Monitor(settings)
    lifecycle = LifecycleManager(store, settings, worker=worker)
    instance_id = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal instance_id
        try:
            instance_id = await asyncio.to_thread(store.initialize)
            if hasattr(store, "acquire_scheduler_lock"):
                await asyncio.to_thread(store.acquire_scheduler_lock)
            if hasattr(store, "reconcile_restart"):
                await asyncio.to_thread(store.reconcile_restart)
            monitor.start()
            yield
        finally:
            try:
                lifecycle.shutdown()
            finally:
                try:
                    monitor.stop()
                finally:
                    store.close()

    app = FastAPI(title="Generation Station", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.lifecycle = lifecycle
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):  # noqa: B008
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), settings.api_token.get_secret_value().encode()
        ):
            raise HTTPException(401, "A valid server access token is required.",
                                headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        # Never expose connection strings or query details to clients.
        return JSONResponse(status_code=503, content={"detail": "Database unavailable. Try again shortly."})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": {
            "code": "RESOURCE_CONFLICT", "message": "A model or profile with that identity already exists.",
            "operation_id": None, "resources": [],
        }})

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": {
            "code": "IDEMPOTENCY_KEY_REUSED", "message": str(exc),
            "operation_id": None, "resources": [],
        }})

    @app.exception_handler(LifecycleError)
    async def lifecycle_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": {
            "code": exc.code, "message": exc.message, "operation_id": exc.operation_id,
            "resources": exc.resources,
        }})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    api = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])

    def snapshot():
        return lifecycle.host_snapshot({**monitor.snapshot(), "instance_id": instance_id})

    @api.get("/host")
    def host():
        return snapshot()

    @api.get("/models")
    def catalog():
        return {"models": store.list_models()}

    @api.get("/profiles")
    def profiles():
        return {"profiles": store.list_profiles()}

    @api.post("/profiles", status_code=201)
    def create_profile(payload: ProfileCreate):
        return {"profile": store.create_profile(payload.model_dump())}

    @api.put("/profiles/{model_id}")
    def update_profile(model_id: str, payload: ProfileUpdate):
        result = store.update_profile(model_id, payload.model_dump())
        if result is None:
            raise HTTPException(404, {"code": "PROFILE_NOT_FOUND", "message": "The profile does not exist."})
        if result.get("busy"):
            raise HTTPException(409, {"code": "MODEL_BUSY", "message": "Profiles cannot change while a worker is active."})
        return {"profile": result}

    @api.delete("/profiles/{model_id}")
    def delete_profile(model_id: str):
        result = store.delete_profile(model_id)
        if result == "missing":
            raise HTTPException(404, {"code": "PROFILE_NOT_FOUND", "message": "The profile does not exist."})
        if result == "busy":
            raise HTTPException(409, {"code": "MODEL_BUSY", "message": "Profiles cannot be deleted while a worker is active."})
        return {"deleted": True, "model_id": model_id}

    @api.post("/models/{model_id}/load", status_code=202)
    def load_model(model_id: str, payload: LoadRequest,
                   idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128)):
        return lifecycle.create_load(model_id, payload.profile_id, idempotency_key, snapshot())

    @api.post("/models/{model_id}/unload", status_code=202)
    def unload_model(model_id: str,
                     idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128)):
        return lifecycle.create_unload(model_id, idempotency_key)

    @api.get("/operations")
    def operation_history(limit: int = 100):
        if not 1 <= limit <= 100:
            raise HTTPException(422, "limit must be between 1 and 100")
        return lifecycle.list_operations(limit)

    @api.get("/operations/{operation_id}")
    def operation(operation_id: str):
        return lifecycle.operation(operation_id)

    @api.get("/events")
    async def events(request: Request):
        async def stream():
            while not await request.is_disconnected():
                yield "event: host\ndata: " + json.dumps(snapshot()) + "\n\n"
                await asyncio.sleep(settings.sample_interval_seconds)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    app.include_router(api)
    # Unknown API routes must not fall through to the frontend.
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
                   dependencies=[Depends(authenticate)])
    def missing_api(path: str):
        raise HTTPException(404, "API route not found")

    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
