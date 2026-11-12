# Model plugins

A plugin teaches Generation Station how to run one kind of local model server. Plugins live in this repository under `backend/generationstation/plugins/` and are registered explicitly; nothing is loaded from outside the repository at runtime.

## What the core does and what a plugin does

The core owns everything that must behave the same for every model: starting the process, writing the plugin's files into a per-start folder, capturing its output, stopping only the process tree it started (checking the process start time so a reused PID is never touched), re-attaching to a ready server after an API restart, detecting a crash, capacity admission against live telemetry, idempotent operations, and the database records.

A plugin supplies only what is specific to its model server:

| Piece | Purpose |
| --- | --- |
| `kind`, `title` | The `kind` value used in `runtimes.json`, and the display name |
| `runtime_model` | A Pydantic model for its `runtimes.json` entry (subclass `BaseRuntime`; presets subclass `BasePreset`). Paths and flags that only the owner of the machine may set go here. |
| `settings` | The settings a user may change, each a `SettingSpec` with a label, bounds or options, unit, help text, and `target` (the server's own name for it). A preset lists which of these it exposes and their defaults. |
| `choice_options()` | Optional: options for a choice setting that depend on the preset (Basalt's `kv`). |
| `estimate()` | RAM and per-GPU free VRAM, in GiB, needed before a start. The default reads the preset's `estimate`; override it when a setting changes the need (Basalt adds `resident_budget_gib`). |
| `launch()` | Returns a `LaunchSpec`: the command line, environment, working folder, and any files (written into the start's own folder before the process starts). |
| `probe()` | Asks the running server whether its model is `loaded`, `loading`, or `failed`; `None` means it is not answering yet. |

The browser can only choose a preset, choose GPUs from the preset's `allowed_gpus`, and change the preset's exposed settings within the plugin's bounds. Every value is validated again on the server. A plugin must never turn a browser value into a path or an unvalidated command-line argument.

GPU indices are NVML/`nvidia-smi` order. Plugins that start CUDA programs should set `CUDA_DEVICE_ORDER=PCI_BUS_ID` so the indices match (Basalt does).

## Adding a plugin

1. Create `backend/generationstation/plugins/<name>.py` with a `RuntimePlugin` subclass. Narrow `kind` with `Literal["<name>"]` in its runtime model.
2. Add an instance to the tuple in `plugins/__init__.py`.
3. Add an entry to `runtimes.example.json` and your local `runtimes.json`, with conservative estimates.
4. Add tests. The parametrized contract test in `backend/tests/test_runtimes.py` checks every registered plugin automatically; add plugin-specific tests for its config and launch output, and a stand-in server (like `tests/fake_basalt.py`) to exercise readiness without loading a model.
5. Load it for real on the desktop once, record the measured RAM and VRAM in `docs/context.md`, and update the estimates.

`basalt.py` is the reference plugin.

## Planned: generation plugins

Media models (YuE2 music, Qwen Image, MiniMax H3 video) have no server of their own. Each will get a small worker, run in its own Python environment so their dependencies do not conflict, that speaks one HTTP contract: `GET /health`, `POST /generate` returning a job ID, and `GET /jobs/{id}`, with outputs written to a folder. The plugin will also describe its generation form (for example lyrics, style, and length for YuE2) so the web app can build a simple page for it without new frontend code. Not implemented yet.
