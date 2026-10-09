import asyncio
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from .config import ROOT, Settings
from .storage import Store
from .telemetry import Monitor


def create_app(settings=None, store=None, monitor=None):
    settings = settings or Settings()
    store = store or Store(settings.database_url.get_secret_value())
    monitor = monitor or Monitor(settings)
    instance_id = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal instance_id
        try:
            instance_id = await asyncio.to_thread(store.initialize)
            monitor.start()
            yield
        finally:
            try:
                monitor.stop()
            finally:
                store.close()

    app = FastAPI(title="Generation Station", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
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

    @app.get("/health")
    def health():
        return {"status": "ok"}

    api = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])

    def snapshot():
        return {**monitor.snapshot(), "instance_id": instance_id}

    @api.get("/host")
    def host():
        return snapshot()

    @api.get("/models")
    def catalog():
        return {"models": [dict(row, state="unavailable", loading_enabled=False)
                           for row in store.list_models()]}

    @api.post("/models/{model_id}/load")
    @api.post("/models/{model_id}/unload")
    def refuse_lifecycle(model_id: str):
        # No worker launch path exists in this milestone, including direct API requests.
        raise HTTPException(409, {"code": "LIFECYCLE_UNAVAILABLE",
                                  "message": "Capacity admission and runtime support are not implemented yet."})

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
