"""Server-side runtime catalog: which real model servers exist and how they may be started.

Each entry in the local `runtimes.json` names a plugin with `kind`; the plugin validates the rest.
The browser chooses a preset and adjusts the settings a plugin exposes; it never supplies paths,
commands, or arbitrary runtime flags.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .plugins import get_plugin, plugin_kinds
from .plugins.base import GIB, BasePreset, BaseRuntime, RuntimePlugin

__all__ = [
    "GIB",
    "Catalog",
    "CatalogError",
    "SettingsError",
    "describe_runtime",
    "estimate_requirements",
    "load_catalog",
    "parse_catalog",
    "resolve_settings",
]


@dataclass
class Catalog:
    runtimes: dict[str, BaseRuntime] = field(default_factory=dict)

    def plugin(self, model_id: str) -> RuntimePlugin:
        return get_plugin(self.runtimes[model_id].kind)


class CatalogError(Exception):
    pass


class SettingsError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_catalog(data) -> Catalog:
    if not isinstance(data, dict) or set(data) - {"runtimes"} or not isinstance(data.get("runtimes", {}), dict):
        raise CatalogError('The runtime catalog must be {"runtimes": {...}}.')
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
    return Catalog(runtimes)


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
            "name": preset.name, "gpus": preset.gpus,
            "allowed_gpus": [{"index": i, "name": names.get(i, f"GPU {i}")} for i in preset.allowed_gpus],
            "settings": settings, "estimate": preset.estimate.model_dump(),
        }
    return {"id": model_id, "kind": runtime.kind, "plugin": plugin.title, "name": runtime.name,
            "workload": runtime.workload, "port": runtime.port, "default_preset": runtime.default_preset,
            "presets": presets}
