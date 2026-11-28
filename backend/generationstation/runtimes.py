"""Server-side runtime catalog: which real model servers exist and how they may be started.

Each entry in the local `runtimes.json` names a plugin with `kind`; the plugin validates the rest.
The browser chooses a preset and adjusts the settings a plugin exposes; it never supplies paths,
commands, or arbitrary runtime flags.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .plugins import get_plugin, plugin_kinds
from .plugins.base import GIB, BasePreset, BaseRuntime, RuntimePlugin, RuntimeQuality
from .providers import PROVIDER_ID, ProviderConfig

__all__ = [
    "GIB",
    "Catalog",
    "CatalogError",
    "ReferenceModel",
    "SettingsError",
    "describe_runtime",
    "estimate_requirements",
    "load_catalog",
    "parse_catalog",
    "resolve_settings",
    "validate_inputs",
]


class ReferenceModel(BaseModel):
    """A model that is not run here, with published scores, charted beside the local models for context."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    workload: str = Field(default="text", min_length=1, max_length=40)
    scores: list[RuntimeQuality] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def one_score_per_metric(self):
        metrics = [score.metric for score in self.scores]
        if len(set(metrics)) != len(metrics):
            raise ValueError(f"{self.name} lists a metric twice.")
        return self


@dataclass
class Catalog:
    runtimes: dict[str, BaseRuntime] = field(default_factory=dict)
    references: list[ReferenceModel] = field(default_factory=list)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)  # hosted chat models, optional (providers.py)

    def plugin(self, model_id: str) -> RuntimePlugin:
        return get_plugin(self.runtimes[model_id].kind)


class CatalogError(Exception):
    pass


class SettingsError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_catalog(data) -> Catalog:
    if not isinstance(data, dict) or set(data) - {"runtimes", "references", "providers"} or not isinstance(data.get("runtimes", {}), dict):
        raise CatalogError('The runtime catalog must be {"runtimes": {...}} with optional "references" and "providers".')
    runtimes = {}
    for model_id, raw in data.get("runtimes", {}).items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", model_id):
            raise CatalogError(f"Invalid runtime id {model_id!r}.")
        kind = raw.get("kind") if isinstance(raw, dict) else None
        plugin = get_plugin(kind) if isinstance(kind, str) else None
        if plugin is None:
            raise CatalogError(f"Runtime {model_id!r}: unknown kind {kind!r}. "
                               f"Available plugins: {', '.join(plugin_kinds())}.")
        try:
            runtime = plugin.runtime_model.model_validate(raw)
            plugin.check_runtime(runtime)
        except (ValidationError, ValueError) as exc:
            raise CatalogError(f"Runtime {model_id!r}: {exc}") from exc
        runtimes[model_id] = runtime
    try:
        references = [ReferenceModel.model_validate(raw) for raw in data.get("references") or []]
    except (ValidationError, TypeError) as exc:
        raise CatalogError(f"References: {exc}") from exc
    providers = {}
    for provider_id, raw in (data.get("providers") or {}).items():
        if not PROVIDER_ID.fullmatch(provider_id):
            raise CatalogError(f"Invalid provider id {provider_id!r}: use lower-case letters, digits, - and _.")
        try:
            providers[provider_id] = ProviderConfig.model_validate(raw)
        except ValidationError as exc:
            raise CatalogError(f"Provider {provider_id!r}: {exc}") from exc
    return Catalog(runtimes, references, providers)


def load_catalog(path: Path | None) -> Catalog:
    """An absent file means no real runtimes are configured; a broken file is an error."""
    if path is None or not Path(path).is_file():
        return Catalog()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"The runtime catalog {path} could not be read: {exc}") from exc
    try:
        return parse_catalog(data)
    except CatalogError as exc:
        raise CatalogError(f"The runtime catalog {path} is invalid. {exc}") from exc


def resolve_settings(plugin: RuntimePlugin, preset: BasePreset, overrides: dict | None, gpus: list[int] | None):
    """Merge and validate user overrides. Only the preset's exposed settings may change."""
    overrides = overrides or {}
    errors = []
    values = dict(preset.settings)
    for key, value in overrides.items():
        if key not in preset.settings:
            errors.append(f"{key} cannot be changed for {preset.name}.")
            continue
        spec = plugin.settings[key]
        if spec.kind == "bool":
            if type(value) is not bool:
                errors.append(f"{spec.label} must be on or off.")
                continue
        elif spec.kind == "choice":
            options = plugin.choice_options(preset, key)
            if value not in options:
                errors.append(f"{spec.label} must be one of {', '.join(options)}.")
                continue
        else:
            if value is None and spec.kind == "optional_int":
                values[key] = None
                continue
            if type(value) is not int:
                errors.append(f"{spec.label} must be a whole number.")
                continue
            unit = f" {spec.unit}" if spec.unit else ""
            if spec.minimum is not None and value < spec.minimum:
                errors.append(f"{spec.label} must be at least {spec.minimum}{unit}.")
                continue
            if spec.maximum is not None and value > spec.maximum:
                errors.append(f"{spec.label} must be at most {spec.maximum}{unit}.")
                continue
        values[key] = value
    chosen = list(preset.gpus if gpus is None else gpus)
    if not chosen:
        errors.append("Choose at least one GPU.")
    elif len(set(chosen)) != len(chosen) or not set(chosen) <= set(preset.allowed_gpus):
        errors.append("The GPU selection is not allowed for this preset.")
    elif (limit := plugin.gpu_limit(preset)) is not None and len(chosen) > limit:
        errors.append(f"{plugin.title} runs on {limit} GPU{'' if limit == 1 else 's'} at a time.")
    else:
        errors.extend(plugin.check_gpus(preset, sorted(chosen)))
    if errors:
        raise SettingsError(errors)
    return values, sorted(chosen)


def estimate_requirements(plugin: RuntimePlugin, runtime: BaseRuntime, preset: BasePreset, values: dict,
                          gpus: list[int], host_gpus: list[dict]):
    """Return (ram_bytes, {gpu_uuid: bytes}) for admission, or raise SettingsError."""
    by_index = {gpu.get("index"): gpu for gpu in host_gpus if isinstance(gpu, dict)}
    for index in gpus:
        gpu = by_index.get(index)
        if gpu is None or not gpu.get("id"):
            raise SettingsError([f"GPU {index} is not reported by this host."])
    ram_gib, gpu_gib = plugin.estimate(runtime, preset, values, gpus)
    return int(ram_gib * GIB), {by_index[index]["id"]: int(need * GIB) for index, need in gpu_gib.items()}


def describe_runtime(model_id: str, runtime: BaseRuntime, host_gpus: list[dict]) -> dict:
    """Catalog entry for the browser: presets and setting definitions, no paths or environment."""
    plugin = get_plugin(runtime.kind)
    names = {gpu.get("index"): gpu.get("name") for gpu in host_gpus if isinstance(gpu, dict)}
    presets = {}
    for key, preset in runtime.presets.items():
        settings = []
        for name, default in preset.settings.items():
            spec = plugin.settings[name]
            settings.append({"key": name, **spec.model_dump(exclude={"target", "options"}), "default": default,
                             "options": plugin.choice_options(preset, name) if spec.kind == "choice" else None})
        presets[key] = {
            "name": preset.name, "description": preset.description, "gpus": preset.gpus,
            "allowed_gpus": [{"index": i, "name": names.get(i, f"GPU {i}")} for i in preset.allowed_gpus],
            "settings": settings, "estimate": preset.estimate.model_dump(),
            "max_gpus": plugin.gpu_limit(preset), "card_notes": getattr(preset, "card_notes", {}) or {},
            "license": preset.license.model_dump() if preset.license else None,
            "quality": preset.quality.model_dump() if preset.quality else None,
            "rankings": [score.model_dump() for score in preset.rankings],
        }
    generation = None
    if plugin.generates:
        fields = lambda specs: [{"key": key, **spec.model_dump()} for key, spec in specs.items()]
        generation = {"output_kind": plugin.output_kind, "inputs": fields(plugin.inputs if plugin.modes else plugin.mode_inputs(None, runtime)),
                      "make_label": plugin.make_label, "result_noun": plugin.result_noun,
                      "modes": [{"key": key, "label": mode.label, "help": mode.help, "inputs": fields(mode.inputs),
                                 "output_kind": mode.output_kind or plugin.output_kind}
                                for key, mode in plugin.modes.items()],
                      "timings": [timing.model_dump() for timing in plugin.timings],
                      "speech": plugin.speech.model_dump() if plugin.speech else None,
                      "image": plugin.image.for_runtime(lambda mode: plugin.mode_inputs(mode or None, runtime)).model_dump() if plugin.image else None,
                      "music": plugin.music.for_runtime(lambda mode: plugin.mode_inputs(mode or None, runtime)).model_dump() if plugin.music else None,
                      "video": plugin.video.for_runtime(lambda mode: plugin.mode_inputs(mode or None, runtime)).model_dump() if plugin.video else None,
                      "transcribe": plugin.transcribe.for_runtime(lambda mode: plugin.mode_inputs(mode or None, runtime)).model_dump() if plugin.transcribe else None}
    return {"id": model_id, "kind": runtime.kind, "plugin": plugin.title, "name": runtime.name,
            "description": runtime.description or plugin.description or None,
            "workload": runtime.workload, "port": runtime.port, "bind": runtime.host, "default_preset": runtime.default_preset,
            "max_gpus": plugin.max_gpus, "presets": presets, "generation": generation, "chat": plugin.chats,
            "assistant": bool(runtime.assistant and plugin.chats),
            "license": runtime.license.model_dump() if runtime.license else None,
            "quality": runtime.quality.model_dump() if runtime.quality else None,
            "rankings": [score.model_dump() for score in runtime.rankings]}


def _valid_crop(value: str) -> bool:
    """A framing box as fractions of the picture: x,y,width,height inside it, not vanishingly small."""
    try:
        x, y, w, h = (float(part) for part in value.split(","))
    except ValueError:
        return False
    return 0 <= x and 0 <= y and 0.05 <= w and 0.05 <= h and x + w <= 1.0001 and y + h <= 1.0001


def validate_inputs(plugin: RuntimePlugin, inputs: dict, uploads=None, runtime=None) -> dict:
    """Check generation-form values against the plugin's input specs. Unknown fields are refused.

    Plugins with modes need "mode"; only that mode's fields are accepted. `uploads(upload_id)` returns an
    upload's record (kind, name, ...) or None; files fields are checked against it.
    """
    if not isinstance(inputs, dict):
        raise SettingsError(["Inputs must be an object."])
    mode = None
    if plugin.modes:
        mode = inputs.get("mode", next(iter(plugin.modes)))
        if mode not in plugin.modes:
            raise SettingsError([f"mode must be one of {', '.join(plugin.modes)}."])
    specs = plugin.mode_inputs(mode, runtime)
    errors, result, files = [], {}, {}
    for key in inputs:
        if key not in specs and not (key == "mode" and plugin.modes):
            errors.append(f"{key} is not an input of {plugin.title}.")
    def chosen(key):
        return inputs.get(key, specs[key].default if key in specs else None)

    for key, spec in specs.items():
        if any(chosen(other) != wanted for other, wanted in spec.show_when.items()):
            continue  # a field that does not apply now (the custom size without resolution "custom")
        value = inputs.get(key, spec.default)
        if value is None or (isinstance(value, (str, list)) and not value) or (isinstance(value, str) and not value.strip()):
            if spec.required:
                errors.append(f"{spec.label} is required.")
            continue
        if spec.kind == "files":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"{spec.label} must be a list of uploaded files.")
                continue
            if spec.max_count and len(value) > spec.max_count:
                errors.append(f"{spec.label} takes at most {spec.max_count}.")
                continue
            records = [uploads(item) if uploads else None for item in value]
            if any(record is None for record in records):
                errors.append(f"{spec.label}: a file is missing or has expired. Add it again.")
                continue
            if any(record["kind"] not in spec.accept for record in records):
                errors.append(f"{spec.label} takes only {' or '.join(spec.accept)} files.")
                continue
            files[key] = [record["kind"] for record in records]
        elif spec.kind == "crop":
            if not isinstance(value, str) or not _valid_crop(value):
                errors.append(f"{spec.label} must be four fractions: x,y,width,height.")
                continue
        elif spec.kind in {"text", "textarea"}:
            if not isinstance(value, str):
                errors.append(f"{spec.label} must be text.")
                continue
            value = value.strip()
            if spec.max_length and len(value) > spec.max_length:
                errors.append(f"{spec.label} is too long (at most {spec.max_length} characters).")
                continue
        elif spec.kind == "choice":
            if value not in spec.options:
                errors.append(f"{spec.label} must be one of {', '.join(spec.options)}.")
                continue
        else:  # int, seed
            if type(value) is not int:
                errors.append(f"{spec.label} must be a whole number.")
                continue
            if (spec.minimum is not None and value < spec.minimum) or (spec.maximum is not None and value > spec.maximum):
                errors.append(f"{spec.label} must be between {spec.minimum} and {spec.maximum}.")
                continue
        result[key] = value
    if not errors:
        errors = plugin.check_inputs(mode, result, files)
    if errors:
        raise SettingsError(errors)
    if mode is not None:
        result = {"mode": mode, **result}
    return result
