import asyncio
import json
import logging
import queue
import re
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .chat import ChatManager
from .chat_tools import HostTools, JobTools, WebTools
from .config import ROOT, Settings
from .generation import GenerationManager
from .host_settings import HostSettings, SettingsInvalid
from .lifecycle import IdempotencyConflict, LifecycleError, LifecycleManager
from .logs import LogNotFound, LogStore
from .process_worker import ProcessSupervisor
from .runtimes import load_catalog
from .storage import Store
from .telemetry import Monitor
from .text_models import TextModelBroker
from .uploads import UploadError, UploadStore


class RequestAccessLogMiddleware:
    """Emit one redacted access record as soon as response headers are sent."""

    def __init__(self, app, logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        logged = False

        def emit(status_code):
            nonlocal logged
            # The router sets this before invoking the endpoint. Never log a
            # raw path: unmatched paths and path parameters can contain secrets.
            route = scope.get("route")
            route_template = getattr(route, "path", "<unmatched>")
            peer = scope.get("client")
            client_ip = peer[0] if peer else None
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": scope.get("method"),
                "route": route_template,
                "client_ip": client_ip,
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            self.logger.info(json.dumps(record, separators=(",", ":")))
            logged = True

        async def logged_send(message):
            if message["type"] == "http.response.start":
                emit(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, logged_send)
        except Exception:
            # Starlette's outer server-error middleware generates the eventual
            # 500 response, which bypasses this inner middleware's send wrapper.
            if not logged:
                emit(500)
            raise


def _access_logger():
    logger = logging.getLogger(f"generationstation.access.{uuid.uuid4().hex}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(message)s")
    log_path = ROOT / "runtime" / "logs" / "access.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for handler in (RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5,
                                        encoding="utf-8"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


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


class RuntimeStartRequest(BaseModel):
    """Preset plus allow-listed settings; values are validated again against the preset."""
    model_config = ConfigDict(extra="forbid")
    preset: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    settings: dict[StrictStr, StrictStr | StrictInt | bool | None] = Field(default_factory=dict)
    gpus: list[StrictInt] | None = Field(default=None, max_length=16)

    @field_validator("settings")
    @classmethod
    def bounded(cls, value):
        if len(value) > 32:
            raise ValueError("Too many settings.")
        return value


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: StrictStr | None = Field(default=None, min_length=1, max_length=64)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr = Field(max_length=200)


class ChatAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: StrictStr = Field(min_length=1, max_length=36)
    name: StrictStr = Field(min_length=1, max_length=200)


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(default="", max_length=20_000)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=6)
    thinking: StrictBool | Annotated[StrictStr, Field(max_length=20)] = True  # a level the model takes, "off", or true/false
    # The page the person is on, for the help assistant ("MiniMax H3 videos & pictures, tab A picture").
    where: StrictStr | None = Field(default=None, max_length=200)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    searxng_url: StrictStr = Field(default="", max_length=300)


class SearchTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    searxng_url: StrictStr | None = Field(default=None, max_length=300)


class SegmentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: StrictInt = Field(ge=0)
    speaker: StrictStr | None = Field(default=None, max_length=80)
    text: StrictStr | None = Field(default=None, max_length=20000)


class TranscriptEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt
    segments: list[SegmentEdit] = Field(default_factory=list, max_length=5000)
    rename: dict[Annotated[str, Field(max_length=80)], Annotated[str, Field(max_length=80)]] = Field(default_factory=dict, max_length=200)


class ActionItemEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: StrictStr = Field(max_length=400)
    owner: StrictStr | None = Field(default=None, max_length=80)
    due: StrictStr | None = Field(default=None, max_length=80)
    time: StrictStr | None = Field(default=None, max_length=80)


class DecisionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: StrictStr = Field(max_length=400)
    by: StrictStr | None = Field(default=None, max_length=80)
    time: StrictStr | None = Field(default=None, max_length=80)


class NotesEdit(BaseModel):
    """Each list sent replaces the saved one; one left out is not touched."""
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt
    summary: list[Annotated[StrictStr, Field(max_length=600)]] | None = Field(default=None, max_length=50)
    actions: list[ActionItemEdit] | None = Field(default=None, max_length=200)
    decisions: list[DecisionEdit] | None = Field(default=None, max_length=200)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[StrictStr, StrictStr | StrictInt | list[StrictStr] | None] = Field(default_factory=dict)

    @field_validator("inputs")
    @classmethod
    def bounded(cls, value):
        if len(value) > 32:
            raise ValueError("Too many inputs.")
        if any(isinstance(item, list) and len(item) > 12 for item in value.values()):
            raise ValueError("Too many files.")
        return value


def create_app(settings=None, store=None, monitor=None, worker=None, catalog=None, runtime_adapter=None):
    settings = settings or Settings()
    store = store if store is not None else Store(settings.database_url.get_secret_value())
    monitor = monitor if monitor is not None else Monitor(settings)
    catalog = catalog if catalog is not None else load_catalog(settings.runtimes_file)
    if runtime_adapter is None and catalog.runtimes:
        runtime_adapter = ProcessSupervisor(settings.runtime_dir)
    lifecycle = LifecycleManager(store, settings, worker=worker, catalog=catalog,
                                 runtime_adapter=runtime_adapter)
    if hasattr(monitor, "watch_processes"):
        monitor.watch_processes(lifecycle.owned_processes, lifecycle.helper_processes)
    uploads = UploadStore(settings.runtime_dir)
    generation = GenerationManager(store, catalog, uploads)
    host_settings = HostSettings(store, settings.searxng_url)
    web_tools = WebTools(host_settings.searxng_url)
    host_settings.web = web_tools
    logs = LogStore(settings.runtime_dir, store)
    host_tools = HostTools(store, catalog, lifecycle, lambda: snapshot())
    chat = ChatManager(store, catalog, generation, uploads, host_tools=host_tools, web_tools=web_tools,
                       job_tools=JobTools(store, catalog, generation, logs))
    # Text models for worker jobs that ask for one (meeting notes); polls only plugins that declare text_model_jobs.
    broker = TextModelBroker(store, catalog, host_tools, chat)
    access_logger = _access_logger()
    instance_id = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal instance_id
        try:
            instance_id = await asyncio.to_thread(store.initialize)
            if hasattr(store, "acquire_scheduler_lock"):
                await asyncio.to_thread(store.acquire_scheduler_lock)
            await asyncio.to_thread(lifecycle.sync_catalog)
            keep = await asyncio.to_thread(lifecycle.recover_runtime_processes)
            if hasattr(store, "reconcile_restart"):
                await asyncio.to_thread(store.reconcile_restart, keep)
            monitor.start()
            if any(getattr(catalog.plugin(m), "text_model_jobs", False) for m in catalog.runtimes):
                broker.start()
            yield
        finally:
            broker.close()
            try:
                lifecycle.shutdown()
            finally:
                try:
                    monitor.stop()
                finally:
                    try:
                        store.close()
                    finally:
                        for handler in access_logger.handlers[:]:
                            handler.close()
                            access_logger.removeHandler(handler)

    app = FastAPI(title="Generation Station", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.lifecycle = lifecycle
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    # Add this after CORS so it wraps preflight responses as well as routed requests.
    app.add_middleware(RequestAccessLogMiddleware, logger=access_logger)
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
    def models_catalog():
        lifecycle.refresh_runtime_health()
        # A runtime taken out of the catalog keeps its row (and its history) in the database but is no longer a model
        # to offer; a simulation profile is listed whether or not the catalog names it.
        return {"models": [model for model in store.list_models()
                           if model["id"] in catalog.runtimes or model["profile"]["id"] is not None]}

    @api.get("/runtimes")
    def runtimes():
        return {"runtimes": lifecycle.runtime_catalog(snapshot())}

    @api.post("/runtimes/{model_id}/start", status_code=202)
    def start_runtime(model_id: str, payload: RuntimeStartRequest,
                      idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128)):
        return lifecycle.create_runtime_load(model_id, payload.preset, payload.settings, payload.gpus,
                                             idempotency_key, snapshot())

    @api.post("/runtimes/{model_id}/estimate")
    def estimate_runtime(model_id: str, payload: RuntimeStartRequest):
        return lifecycle.estimate_runtime(model_id, payload.preset, payload.settings, payload.gpus, snapshot())

    @api.post("/models/{model_id}/jobs", status_code=202)
    def create_job(model_id: str, payload: JobRequest):
        return generation.create(model_id, payload.inputs)

    @api.get("/jobs")
    def jobs(model_id: str | None = None, limit: int = 50):
        if not 1 <= limit <= 200:
            raise HTTPException(422, "limit must be between 1 and 200")
        return generation.list(model_id, limit)

    @api.get("/jobs/{job_id}")
    def job(job_id: str):
        return generation.get(job_id)

    @api.post("/uploads", status_code=201)
    async def upload(request: Request, name: str = Query(min_length=1, max_length=200)):
        """A file for a generation request, sent as the raw request body; returns its ID for the job's inputs."""
        try:
            return await uploads.save_stream(name, request.stream())
        except UploadError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/jobs/{job_id}/inputs/{name}")
    def job_input(job_id: str, name: str):
        path, mime = generation.input_path(job_id, name)
        return FileResponse(path, media_type=mime, filename=name)

    @api.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return generation.cancel(job_id)

    @api.delete("/jobs/{job_id}")
    def delete_job(job_id: str):
        return generation.delete(job_id)

    @api.put("/jobs/{job_id}/transcript")
    def edit_transcript(job_id: str, request: TranscriptEdit):
        return generation.edit_transcript(job_id, request.model_dump())

    @api.put("/jobs/{job_id}/notes")
    def edit_notes(job_id: str, request: NotesEdit):
        return generation.edit_notes(job_id, request.model_dump())

    @api.get("/jobs/{job_id}/files/{name}")
    def job_file(job_id: str, name: str):
        path, mime = generation.output_path(job_id, name)
        return FileResponse(path, media_type=mime, filename=name)

    @api.get("/assistant")
    def assistant():
        """The help assistant's ongoing conversation, created when there is none."""
        return chat.assistant()

    @api.post("/assistant/new")
    def assistant_new():
        """Start the help assistant over: a new conversation (the old one stays on the Chat page)."""
        return chat.assistant(fresh=True)

    @api.get("/conversations")
    def conversations():
        return chat.list()

    @api.post("/conversations", status_code=201)
    def create_conversation(payload: ConversationCreate):
        return chat.create(payload.model_id)

    @api.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        return chat.get(conversation_id)

    @api.put("/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, payload: ConversationRename):
        return chat.rename(conversation_id, payload.title)

    @api.delete("/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str):
        return chat.delete(conversation_id)

    @api.post("/conversations/{conversation_id}/stop")
    def stop_conversation(conversation_id: str):
        return chat.stop(conversation_id)

    @api.post("/conversations/{conversation_id}/messages")
    def send_message(conversation_id: str, payload: ChatMessageRequest):
        """Answer a message as server-sent events: message (each saved message), start, delta, error, done.
        The answer finishes and is saved even if the browser disconnects."""
        turn = chat.start(conversation_id, payload.text, [a.model_dump() for a in payload.attachments],
                          payload.thinking, payload.where)

        async def stream():
            while True:
                try:
                    event, data = await asyncio.to_thread(turn.events.get, True, 15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
                if event == "done":
                    return
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @api.get("/settings")
    def host_settings_get():
        return host_settings.get()

    @api.put("/settings")
    def host_settings_put(payload: SettingsUpdate):
        try:
            return host_settings.set(payload.searxng_url)
        except SettingsInvalid as exc:
            raise HTTPException(422, {"code": "SETTINGS_INVALID", "message": str(exc)}) from None

    @api.post("/settings/test-search")
    def host_settings_test(payload: SearchTest):
        try:
            return host_settings.test_search(payload.searxng_url)
        except SettingsInvalid as exc:
            return {"ok": False, "message": str(exc)}

    @api.get("/logs")
    def log_list():
        """Model server logs, one per start, newest first, with that start's model and outcome."""
        return logs.list()

    @api.get("/logs/{name}")
    def log_text(name: str, lines: int = Query(default=500, ge=1, le=5000)):
        try:
            return logs.read(name, lines)
        except LogNotFound:
            raise HTTPException(404, {"code": "LOG_NOT_FOUND", "message": "That log is not available."}) from None

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
                await asyncio.to_thread(lifecycle.refresh_runtime_health)
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
