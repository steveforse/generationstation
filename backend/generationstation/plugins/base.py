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
    # How options read in the browser, where the stored value is a code ("cpu" -> "CPU (system RAM)").
    # Without one, an option is shown with a capital first letter (codes such as "q8_0" in capitals).
    option_labels: dict[str, str] = Field(default_factory=dict)
    help: str
    # Shown under "Advanced settings" instead of with the main choices.
    advanced: bool = False


class InputSpec(BaseModel):
    """One field of a generation form (what the person types to make a song, image, ...).

    A "files" field takes uploads: `accept` names the kinds ("image", "video", "audio", "transcript") and
    `max_count` how many. Its value is a list of upload IDs; the worker receives the files' paths.
    A "crop" field is the framing of the picture in the files field `target`, chosen on a preview when the
    shape (`shape_field`, whose options carry their proportions such as "16:9") differs from the picture's:
    "x,y,w,h" as fractions of the picture.
    """
    model_config = ConfigDict(frozen=True)
    label: str
    kind: Literal["text", "textarea", "int", "choice", "seed", "files", "crop"]
    required: bool = False
    default: str | int | None = None
    minimum: int | None = None
    maximum: int | None = None
    max_length: int | None = None
    options: tuple[str, ...] = ()
    option_labels: dict[str, str] = Field(default_factory=dict)
    placeholder: str | None = None
    help: str
    advanced: bool = False
    accept: tuple[Literal["image", "video", "audio", "transcript"], ...] = ()
    max_count: int | None = Field(default=None, ge=1, le=12)
    target: str | None = None
    shape_field: str | None = None
    # The field applies only while other fields have these values (for example the custom size only for
    # resolution "custom"): the browser shows it only then, and the server ignores it otherwise.
    show_when: dict[str, str] = Field(default_factory=dict)
    # A width field locked to a height field (and the other way round) in the proportions of `shape_field`,
    # or of the picture in the mode's files fields for "match picture". Display only, like show_when.
    # A longer how-to shown as a fold-out under the field: one tip per entry ("Heading: text").
    guide: tuple[str, ...] = ()
    ratio_partner: str | None = None
    ratio_role: Literal["width", "height"] | None = None


class ModeSpec(BaseModel):
    """One way of making something, shown as a tab with its own form (for example "From a picture")."""
    model_config = ConfigDict(frozen=True)
    label: str
    help: str
    inputs: dict[str, InputSpec]
    # What this mode makes when it differs from the plugin's output_kind (H3 makes pictures as well as videos).
    output_kind: Literal["audio", "image", "video", "document"] | None = None


class TimingSpec(BaseModel):
    """A measured time for one result, shown on the form before it is made.

    The first timing whose conditions all match is used: `when` names form inputs and values,
    `preset` and `gpu` the model and card it ran on. `first_seconds` is the first result after a
    start, which includes one-off preparation. Record only measured times, with what was measured.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    seconds: float = Field(gt=0)
    first_seconds: float | None = Field(default=None, gt=0)
    when: dict[str, str] = Field(default_factory=dict)
    preset: str | None = None
    gpu: int | None = None
    note: str | None = Field(default=None, max_length=120)


class Estimate(BaseModel):
    """Conservative start requirements. Estimates, not measurements; edit them as you measure."""
    model_config = ConfigDict(extra="forbid")
    ram_gib: float = Field(gt=0, description="RAM needed at start.")
    gpu_min_free_gib: dict[int, float] = Field(description="Free VRAM needed per GPU index before start.")


class RuntimeLicense(BaseModel):
    """What a model may be used for, shown on the Models page. A reading of the licences, not legal advice.

    use: "work" is free for a company's own use as far as the licences say; "conditions" is free with limits to check
    (a revenue cap, a ban on hosted services); "personal" is non-commercial or limited by territory, so keep it to
    your own machine and your own use."""
    model_config = ConfigDict(extra="forbid")
    use: Literal["work", "conditions", "personal"]
    weights: str = Field(min_length=1, max_length=160, description="The model weights' licence, e.g. Apache-2.0.")
    code: str | None = Field(default=None, max_length=160, description="The runtime code's licence.")
    note: str | None = Field(default=None, max_length=700, description="The terms that matter, in plain words.")
    url: str | None = Field(default=None, max_length=300, pattern=r"^https://", description="Where the licence is.")


class RuntimeQuality(BaseModel):
    """A published quality score for a model, charted on the Models page against others measured the same way."""
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(min_length=1, max_length=80, description="What the score is, e.g. 'Arena Elo (TTS Arena)'.")
    score: float
    estimated: bool = Field(default=False, description="True when the score is not published for this exact build.")
    source: str | None = Field(default=None, max_length=300, pattern=r"^https://", description="Where the score is published.")
    as_of: str | None = Field(default=None, max_length=20, description="When the score was read, e.g. 2026-11-26.")
    note: str | None = Field(default=None, max_length=500, description="How an estimate was made, or what the score covers.")


class BasePreset(BaseModel):
    """Fields every preset has. Plugins subclass this to add their own (model path, flags)."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500, description="What this model is good at, for the UI.")
    gpus: list[int] = Field(min_length=1, description="Default GPU indices, in NVML/PCI order.")
    allowed_gpus: list[int] | None = None
    settings: dict[str, SettingValue] = Field(default_factory=dict)
    estimate: Estimate
    license: RuntimeLicense | None = Field(
        default=None, description="Overrides the model's licence for this preset, when versions differ.")
    quality: RuntimeQuality | None = Field(
        default=None, description="Overrides the model's quality score for this preset (for example a smaller quant).")
    rankings: list[RuntimeQuality] = Field(
        default_factory=list, description="Further scores on other metrics, charted as extra rankings. Per metric, these replace the model's score for this version.")

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
    description: str | None = Field(default=None, max_length=500, description="Overrides the plugin's description.")
    workload: str = Field(min_length=1, max_length=40)
    port: int = Field(ge=1024, le=65535)
    host: Literal["127.0.0.1", "0.0.0.0"] = Field(
        default="127.0.0.1", description="Where the model's own server listens: this computer only, or every network interface "
        "(for tools on other machines; the model's server has no login of its own, so only on a network you trust).")
    ready_timeout_seconds: float = Field(default=1500, gt=0, le=7200)
    stop_timeout_seconds: float = Field(default=30, gt=0, le=600)
    default_preset: str
    presets: dict[str, BasePreset] = Field(min_length=1)
    license: RuntimeLicense | None = None
    quality: RuntimeQuality | None = None
    rankings: list[RuntimeQuality] = Field(
        default_factory=list, description="Further scores on other metrics, charted as extra rankings next to `quality`.")
    # The text model the help assistant (the bubble on every page) runs on. At most one; a chat model.
    assistant: bool = False

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
    # One or two plain sentences on what the server does; runtimes.json may override it per entry.
    description: ClassVar[str] = ""
    runtime_model: ClassVar[type[BaseRuntime]]
    settings: ClassVar[dict[str, SettingSpec]] = {}
    max_gpus: ClassVar[int | None] = None
    # A plugin that makes things (songs, images) lists its form fields and implements submit/job_status.
    # With several ways of making something, it lists `modes` instead, each with its own fields; the
    # chosen mode arrives as the input "mode".
    inputs: ClassVar[dict[str, InputSpec]] = {}
    modes: ClassVar[dict[str, ModeSpec]] = {}
    output_kind: ClassVar[str | None] = None  # "audio", "image", "video" or "document" (text files)
    text_model_jobs: ClassVar[bool] = False  # its jobs may ask the host for a running text model (text_models.py)
    # Other programs whose GPU memory belongs to this model while it runs (display only): Drama 3 runs inside WSL,
    # whose GPU memory Windows charges to the virtual machine's process, vmwp.
    gpu_helpers: ClassVar[tuple[str, ...]] = ()
    # The button and the word for one result, when the output kind's own ("Make a song", "song") do not fit.
    make_label: ClassVar[str | None] = None
    result_noun: ClassVar[str | None] = None
    timings: ClassVar[tuple[TimingSpec, ...]] = ()  # measured times per setting, for the form
    # A server that answers chat (an OpenAI-style /v1/chat/completions): the dashboard offers it on the Chat page.
    chats: ClassVar[bool] = False

    @property
    def generates(self) -> bool:
        return bool(self.inputs or self.modes)

    def mode_inputs(self, mode: str | None, runtime: BaseRuntime | None = None) -> dict[str, InputSpec] | None:
        """The fields of a mode (or of the only form, for plugins without modes); None for an unknown mode. A plugin whose
        models differ in what they take (some read pictures, some do not) narrows the form to the `runtime`'s."""
        if not self.modes:
            return self.inputs
        return self.modes[mode].inputs if mode in self.modes else None

    def check_inputs(self, mode: str | None, values: dict, files: dict) -> list[str]:
        """Rules across fields, after each field is valid. `files` maps a files field to its uploads' kinds.
        Return problems in plain words; an empty list means the request is fine."""
        return []

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

    def gpu_limit(self, preset: BasePreset) -> int | None:
        """How many GPUs one start may use; None means no limit."""
        return self.max_gpus

    def check_gpus(self, preset: BasePreset, gpus: list[int]) -> list[str]:
        """Problems with a GPU choice beyond the allowed list and the limit, in plain words."""
        return []

    def chat_sampling(self, preset: BasePreset, gpus: list[int]) -> dict:
        """Sampling the chat sends when the person sets none (for servers whose own default is greedy)."""
        return {}

    def chat_thinking(self, preset: BasePreset, gpus: list[int]) -> dict | None:
        """The thinking levels a chat may ask this model for on these cards: {"levels": [...] lowest first,
        "default": level, "off": whether thinking can be turned off}, or None when the model does not chat."""
        return None

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

    # ----- generation (only for plugins with `inputs`) --------------------------------------

    def output_dir(self, runtime: BaseRuntime) -> Path:
        raise NotImplementedError

    def submit(self, runtime: BaseRuntime, job_id: str, inputs: dict) -> dict:
        """Queue a job on the running server. Return the worker's job record."""
        raise NotImplementedError

    def cancel(self, runtime: BaseRuntime, job_id: str) -> dict | None:
        """Ask the running server to cancel a job. Return its record, {"status": "missing"} if it does
        not know the job, or None if it is not answering."""
        raise NotImplementedError

    def job_status(self, runtime: BaseRuntime, job_id: str) -> dict | None:
        """Return the worker's job record, or None if the server is not answering."""
        raise NotImplementedError
