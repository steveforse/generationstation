"""The contract every model plugin implements.

A plugin describes one kind of local model server: what its `runtimes.json` section may contain,
which settings a user may change (with bounds), how much memory a start needs, how to launch it,
and how to tell when it is ready. Generation Station's core owns everything else: process start
and stop, ownership checks, restart re-adoption, crash detection, admission and persistence.

Plugins live in this repository and are registered explicitly in `plugins/__init__.py`.
The browser can only pick a preset, GPUs, and the settings a plugin exposes; it never supplies
paths, commands, or arbitrary flags.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GIB = 1024**3

SettingValue = str | int | bool | None


class SettingSpec(BaseModel):
    """One user-adjustable setting. `target` is the plugin's own name for it (a flag or config key)."""
    model_config = ConfigDict(frozen=True)
    label: str
    target: str
    kind: Literal["int", "bool", "choice", "optional_int"]
    minimum: int | None = None
    maximum: int | None = None
    unit: str | None = None
    options: tuple[str, ...] = ()
    help: str


class Estimate(BaseModel):
    """Conservative start requirements. Estimates, not measurements; edit them as you measure."""
    model_config = ConfigDict(extra="forbid")
    ram_gib: float = Field(gt=0, description="RAM needed at start.")
    gpu_min_free_gib: dict[int, float] = Field(description="Free VRAM needed per GPU index before start.")


class BasePreset(BaseModel):
    """Fields every preset has. Plugins subclass this to add their own (model path, flags)."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    gpus: list[int] = Field(min_length=1, description="Default GPU indices, in NVML/PCI order.")
    allowed_gpus: list[int] | None = None
    settings: dict[str, SettingValue] = Field(default_factory=dict)
    estimate: Estimate

    @model_validator(mode="after")
    def check_gpus(self):
        if self.allowed_gpus is None:
            self.allowed_gpus = list(self.gpus)
        if not set(self.gpus) <= set(self.allowed_gpus):
            raise ValueError("Default GPUs must be within allowed_gpus.")
        if set(self.estimate.gpu_min_free_gib) - set(self.allowed_gpus):
            raise ValueError("Estimates may only name allowed GPUs.")
        return self


class BaseRuntime(BaseModel):
    """Fields every runtime entry has. Plugins subclass this and narrow `presets`."""
    model_config = ConfigDict(extra="forbid")
    kind: str
    name: str = Field(min_length=1, max_length=200)
    workload: str = Field(min_length=1, max_length=40)
    port: int = Field(ge=1024, le=65535)
    ready_timeout_seconds: float = Field(default=1500, gt=0, le=7200)
    stop_timeout_seconds: float = Field(default=30, gt=0, le=600)
    default_preset: str
    presets: dict[str, BasePreset] = Field(min_length=1)

    @model_validator(mode="after")
    def default_exists(self):
        if self.default_preset not in self.presets:
            raise ValueError("default_preset must name one of the presets.")
        return self


@dataclass
class LaunchSpec:
    """Everything needed to start the server process. `files` are written to the launch folder first."""
    argv: list[str]
    env: dict[str, str]
    cwd: str | None = None
    files: dict[str, str] = field(default_factory=dict)


ProbeStatus = Literal["loaded", "loading", "failed"]


class RuntimePlugin:
    """Base class for plugins. Override the class attributes and `launch`/`probe`."""

    kind: ClassVar[str]
    title: ClassVar[str]
    runtime_model: ClassVar[type[BaseRuntime]]
    settings: ClassVar[dict[str, SettingSpec]] = {}

    # ----- catalog -----------------------------------------------------------------------

    def check_runtime(self, runtime: BaseRuntime):
        """Validate presets against this plugin's settings. Raise ValueError with a clear message."""
        for key, preset in runtime.presets.items():
            unknown = set(preset.settings) - set(self.settings)
            if unknown:
                raise ValueError(f"Preset {key}: unknown settings {', '.join(sorted(unknown))}.")
            for name, value in preset.settings.items():
                options = self.choice_options(preset, name)
                if self.settings[name].kind == "choice" and value not in options:
                    raise ValueError(f"Preset {key}: {name} must be one of {', '.join(options)}.")

    def choice_options(self, preset: BasePreset, name: str) -> list[str]:
        return list(self.settings[name].options)

    # ----- capacity ----------------------------------------------------------------------

    def estimate(self, runtime: BaseRuntime, preset: BasePreset, values: dict, gpus: list[int]):
        """Return (ram_gib, {gpu_index: free_gib_needed}). Override when settings change the need."""
        return preset.estimate.ram_gib, {i: preset.estimate.gpu_min_free_gib[i]
                                         for i in gpus if i in preset.estimate.gpu_min_free_gib}

    # ----- process -----------------------------------------------------------------------

    def launch(self, runtime: BaseRuntime, preset: BasePreset, values: dict, gpus: list[int],
               base_env: dict[str, str], launch_dir: Path) -> LaunchSpec:
        """Describe the process. `launch_dir` is this start's own folder; `files` are written there."""
        raise NotImplementedError

    def probe(self, runtime: BaseRuntime) -> ProbeStatus | None:
        """Ask the running server whether its model is loaded. None means it is not answering."""
        raise NotImplementedError
