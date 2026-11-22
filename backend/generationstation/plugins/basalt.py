"""Basalt: native-Windows LLM server (`basalt.exe serve --config FILE`, OpenAI-style API)."""
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field

from .base import BasePreset, BaseRuntime, LaunchSpec, RuntimePlugin, SettingSpec


class BasaltPreset(BasePreset):
    alias: str = Field(min_length=1, max_length=200)
    model_path: str = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)
    fixed: dict[str, str | int | bool] = Field(default_factory=dict,
                                               description="Basalt keys always written; not user-editable.")
    kv_options: list[str] = Field(default_factory=list)


class BasaltRuntime(BaseRuntime):
    kind: Literal["basalt"]
    executable: str = Field(min_length=1)
    leading_args: list[str] = Field(default_factory=list, description="For tests; normally empty.")
    working_dir: str | None = None
    path_prepend: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    presets: dict[str, BasaltPreset] = Field(min_length=1)


class BasaltPlugin(RuntimePlugin):
    kind = "basalt"
    title = "Basalt"
    description = "Runs a large language model for chat and coding, answering through an OpenAI-style API."
    runtime_model = BasaltRuntime
    settings: ClassVar[dict[str, SettingSpec]] = {
        "max_context": SettingSpec(
            label="Max context", target="max-context", kind="int", minimum=1024, maximum=1_048_576,
            unit="tokens", help="Longest conversation the model accepts."),
        "kv": SettingSpec(
            label="KV cache precision", target="kv", kind="choice",
            help="Lower precision fits more context in VRAM at a small quality cost."),
        "vram_reserve_mib": SettingSpec(
            label="VRAM left free on the main card", target="vram-reserve-mib", kind="int",
            minimum=256, maximum=32768, unit="MiB",
            help="Basalt fills the main card except this amount. Windows refuses less than 256 MiB."),
        "peer_reserve_mib": SettingSpec(
            label="VRAM left free on the second card", target="peer-reserve-mib", kind="int",
            minimum=0, maximum=16384, unit="MiB",
            help="Raise it when the start says the peer's buffers do not fit."),
        "resident_budget_gib": SettingSpec(
            label="RAM for overflow experts", target="resident-budget-gib", kind="optional_int",
            minimum=1, maximum=1024, unit="GiB",
            help="Experts that do not fit in VRAM are held in RAM, hottest first. Empty means automatic."),
        "resident_experts": SettingSpec(
            label="Keep overflow experts in RAM", target="resident-experts", kind="bool",
            help="Flash-Next only. Off reads overflow experts from the SSD instead."),
        "ram_reserve_mib": SettingSpec(
            label="RAM left for Windows", target="ram-reserve-mib", kind="int", minimum=0, maximum=262144,
            unit="MiB", help="0 turns Basalt's RAM guard off; only safe when nothing else needs the RAM."),
        "conversation_cache_mib": SettingSpec(
            label="Conversation cache", target="conversation-cache-mib", kind="int", minimum=0,
            maximum=262144, unit="MiB", help="RAM for parked conversations. 0 turns it off."),
    }

    def choice_options(self, preset, name):
        return list(preset.kv_options) if name == "kv" else super().choice_options(preset, name)

    def estimate(self, runtime, preset, values, gpus):
        ram, gpu = super().estimate(runtime, preset, values, gpus)
        budget = values.get("resident_budget_gib")
        return ram + (budget if isinstance(budget, int) else 0), gpu

    def config(self, runtime: BasaltRuntime, preset: BasaltPreset, values: dict, gpus: list[int]) -> dict:
        entry = {"alias": preset.alias, "model": preset.model_path, "gpu": ",".join(str(g) for g in gpus)}
        entry.update(preset.fixed)
        for key, value in values.items():
            if value is not None:  # None means automatic: let Basalt choose
                entry[self.settings[key].target] = value
        return {"version": 2, "server": {"host": "127.0.0.1", "port": runtime.port}, "models": [entry]}

    def environment(self, runtime: BasaltRuntime, preset: BasaltPreset, base_env: dict) -> dict:
        env = dict(base_env)
        env.update(runtime.env)
        env.update(preset.env)
        # Make CUDA indices match NVML/nvidia-smi order, which the telemetry and UI use.
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        if runtime.path_prepend:
            env["PATH"] = ";".join(runtime.path_prepend + [env.get("PATH", "")])
        return env

    def launch(self, runtime, preset, values, gpus, base_env, launch_dir: Path):
        config_path = Path(launch_dir) / "basalt-config.json"
        return LaunchSpec(
            argv=[runtime.executable, *runtime.leading_args, "serve", "--config", str(config_path)],
            env=self.environment(runtime, preset, base_env),
            cwd=runtime.working_dir,
            files={"basalt-config.json": json.dumps(self.config(runtime, preset, values, gpus), indent=2)},
        )

    def probe(self, runtime):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{runtime.port}/v1/models", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        statuses = set()
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            for key in ("status", "state"):
                value = item.get(key)
                if isinstance(value, dict):  # Basalt reports {"value": "loaded"}
                    value = value.get("value")
                if isinstance(value, str):
                    statuses.add(value)
        if "loaded" in statuses:
            return "loaded"
        if "failed" in statuses:
            return "failed"
        return "loading"
