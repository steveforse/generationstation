# Generation Station

Generation Station is a browser dashboard for managing AI model processes on a separate Windows desktop. The desktop provides host telemetry and runs inference; a laptop connects through a browser, currently over Tailscale.

## Current state

The M1/M2 prototype is implemented and host-side desktop checks pass: fresh Windows RAM/NVML telemetry, Tailscale API reachability with bearer authentication, PostgreSQL at Alembic `0002 (head)`, and a fake-worker load/unload cycle with zero active reservations afterward. The Windows backend suite passed 69 tests, the PostgreSQL migration/persistence test passed on a disposable database, Ruff passed, and the frontend build plus 11 Playwright tests pass. The laptop browser's full remote connect/reconnect flow remains to be verified. The fake worker performs no inference and loads no weights; no real model is promised to fit or run. Selecting the first M3 workload, model, and runtime remains open.

## Start local development

Requirements: Docker Desktop with Compose, `uv`, [Node.js 24 LTS](https://nodejs.org/en/about/previous-releases) with npm, and PowerShell. Install `uv` on Windows with `winget install --id=astral-sh.uv -e`, or follow the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/). See [docs/development.md](docs/development.md) for full setup, migrations, build, API token use, Tailscale connection settings, and safe database backup/restore.

From the repository root in PowerShell:

```powershell
uv python install 3.12
uv sync --locked --project backend --python 3.12
uv run --project backend python scripts/init_env.py
docker compose up -d --wait db
uv run --locked --project backend alembic -c backend/alembic.ini upgrade head
```

Then start the API in one terminal and the frontend in another:

```powershell
uv run --locked --project backend uvicorn generationstation.app:create_app --factory --host 0.0.0.0 --port 8000
```

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the Vite URL printed in the frontend terminal (normally `http://localhost:5173`). The local API is at `http://127.0.0.1:8000`; its health endpoint is `/health`. API routes require the bearer token generated into the private root `.env` file. Never put the token in a URL, commit `.env`, or share it in logs or screenshots.

To stop local services, stop the API and frontend with Ctrl+C and run `docker compose down`. This keeps the named database volume. Do not add `-v` unless you intend to erase the database.

Project decisions and milestone acceptance criteria are in [docs/context.md](docs/context.md) and [docs/plan.md](docs/plan.md). The session continuity page is [HANDOFF.md](HANDOFF.md).
