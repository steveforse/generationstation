"""Text models: one entry per model, whatever program runs it.

A preset lists, per card choice ("0", "1" or "0,1"), the engine that runs the model there and its files: Basalt
(`basalt.exe serve --config FILE`) or Strata (its Python server in front of its engine). The person only picks the
model's card and plain settings; which engine runs is decided here and never shown. Both engines answer OpenAI-style
chat on the runtime's port, so the chat page and the readiness probe treat them alike.
"""
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import BasePreset, BaseRuntime, Estimate, LaunchSpec, RuntimePlugin, SettingSpec
from .worker import WORKERS_DIR


class CardSetup(BaseModel):
    """How the model runs on one card choice."""
    model_config = ConfigDict(extra="forbid")
    engine: Literal["basalt", "strata"]
    estimate: Estimate
    env: dict[str, str] = Field(default_factory=dict)
    # Basalt
    executable: str | None = None
    working_dir: str | None = None
    path_prepend: list[str] = Field(default_factory=list)
    alias: str | None = None
    model_path: str | None = None
    fixed: dict[str, str | int | bool] = Field(default_factory=dict, description="Engine keys always written.")
    # Strata
    python: str | None = None
    server_dir: str | None = None
    component: str | None = None
    pack: str | None = None
    vision_pack: str | None = None
    tokenizer: str | None = None
    arch: str | None = None
    model_name: str | None = None
    drafter: str | None = None
    # Run Strata's server through workers/strata_inkling_thinking.py, which lets Inkling 2 Mini's thinking levels
    # through (Strata itself forces thinking off and drops the model's thinking text).
    inkling_thinking: bool = False
    # Sampling the chat sends when the person sets none (Strata decodes greedily without it).
    sampling: dict[str, float | int] = Field(default_factory=dict)
    # The thinking levels the engine accepts for this model here, lowest first, as the request's reasoning_effort
    # names them; only these are offered in the chat. Empty: the model does not think here.
    thinking_levels: list[str] = Field(default_factory=list)
    thinking_default: str | None = None
    thinking_off: bool = True  # whether a request can turn thinking off

    @model_validator(mode="after")
    def complete(self):
        need = ("executable", "alias", "model_path") if self.engine == "basalt" else \
            ("python", "server_dir", "component", "pack", "tokenizer", "arch", "model_name")
        missing = [name for name in need if not getattr(self, name)]
        if missing:
            raise ValueError(f"{self.engine} card setup needs {', '.join(missing)}.")
        if len(set(self.thinking_levels)) != len(self.thinking_levels) or "off" in self.thinking_levels:
            raise ValueError("thinking_levels must be distinct level names, without \"off\".")
        if self.thinking_default is not None and self.thinking_default not in self.thinking_levels:
            raise ValueError(f"thinking_default {self.thinking_default!r} is not one of thinking_levels.")
        if self.inkling_thinking and self.engine != "strata":
            raise ValueError("inkling_thinking only applies to Strata.")
        return self


class LLMPreset(BasePreset):
    cards: dict[str, CardSetup] = Field(min_length=1, description='Keyed by the card choice: "0", "1" or "0,1".')
    # One line per card choice on how the model behaves there, shown under the card picker.
    card_notes: dict[str, str] = Field(default_factory=dict)
    kv_options: list[str] = Field(default_factory=list)
    vision_options: list[str] = Field(default_factory=lambda: ["card", "off"])

    @model_validator(mode="after")
    def cards_are_allowed(self):
        for key in self.cards:
            if not set(card_indices(key)) <= set(self.allowed_gpus or self.gpus):
                raise ValueError(f"Card setup {key!r} names a GPU outside allowed_gpus.")
        if card_key(self.gpus) not in self.cards:
            raise ValueError("The default GPUs need a card setup.")
        return self


class LLMRuntime(BaseRuntime):
    kind: Literal["llm"]
    presets: dict[str, LLMPreset] = Field(min_length=1)


def card_key(gpus) -> str:
    return ",".join(str(g) for g in sorted(gpus))


def card_indices(key: str) -> list[int]:
    return [int(part) for part in key.split(",") if part.strip()]


BASALT_KEYS = {"max_context": "max-context", "kv": "kv", "vram_reserve_mib": "vram-reserve-mib",
               "peer_reserve_mib": "peer-reserve-mib", "resident_budget_gib": "resident-budget-gib",
               "resident_experts": "resident-experts", "ram_reserve_mib": "ram-reserve-mib",
               "conversation_cache_mib": "conversation-cache-mib"}
BASALT_VISION = {"card": "dynamic", "processor": "cpu", "off": "off"}


class LLMPlugin(RuntimePlugin):
    kind = "llm"
    title = "Text model"
    description = "A language model for chat. It can look at pictures and start the other models' jobs."
    runtime_model = LLMRuntime
    chats = True
    settings: ClassVar[dict[str, SettingSpec]] = {
        "max_context": SettingSpec(
            label="Context length", target="max_context", kind="int", minimum=4096, maximum=1_048_576, unit="tokens",
            advanced=True, help="How much of a conversation the model keeps in mind. Longer takes more memory on the card."),
        "vision": SettingSpec(
            label="Read pictures", target="vision", kind="choice", options=("card", "processor", "off"),
            option_labels={"card": "On", "processor": "On, on the processor (slower)", "off": "Off"},
            help="Lets the model look at pictures and video stills in a chat."),
        "kv": SettingSpec(
            label="Memory precision", target="kv", kind="choice", advanced=True,
            option_labels={"fp16": "Full (16-bit)", "fp8": "Compact (8-bit)", "int8": "Compact (8-bit)",
                           "k8v4": "Smaller (8/4-bit)", "q4_0": "Smallest (4-bit)"},
            help="How precisely the conversation is held. Compact fits a longer context in the same memory."),
        "vram_reserve_mib": SettingSpec(
            label="VRAM left free on the card", target="vram_reserve_mib", kind="int", minimum=256, maximum=32768,
            unit="MiB", advanced=True, help="The model fills its card except this amount. Windows needs at least 256 MiB."),
        "peer_reserve_mib": SettingSpec(
            label="VRAM left free on the second card", target="peer_reserve_mib", kind="int", minimum=0, maximum=16384,
            unit="MiB", advanced=True, help="On two cards: raise it when a start says the second card's buffers do not fit."),
        "resident_budget_gib": SettingSpec(
            label="RAM for the model's overflow", target="resident_budget_gib", kind="optional_int", minimum=1,
            maximum=1024, unit="GiB", advanced=True,
            help="Parts of the model that do not fit on the card are kept in RAM. Empty means automatic."),
        "resident_experts": SettingSpec(
            label="Keep the overflow in RAM", target="resident_experts", kind="bool", advanced=True,
            help="Off reads the overflow from the SSD instead, which is slower but saves RAM."),
        "ram_reserve_mib": SettingSpec(
            label="RAM left for Windows", target="ram_reserve_mib", kind="int", minimum=0, maximum=262144, unit="MiB",
            advanced=True, help="0 turns the RAM guard off; only safe when nothing else needs the RAM."),
        "conversation_cache_mib": SettingSpec(
            label="Conversation cache", target="conversation_cache_mib", kind="int", minimum=0, maximum=262144,
            unit="MiB", advanced=True, help="RAM for set-aside conversations, so going back to one is quick. 0 turns it off."),
    }

    def choice_options(self, preset, name):
        if name == "kv":
            return list(preset.kv_options)
        if name == "vision":
            return list(preset.vision_options)
        return super().choice_options(preset, name)

    def gpu_limit(self, preset) -> int:
        return max(len(card_indices(key)) for key in preset.cards)

    def check_gpus(self, preset, gpus) -> list[str]:
        if card_key(gpus) in preset.cards:
            return []
        choices = " or ".join(card_key(card_indices(key)) for key in preset.cards)
        return [f"{preset.name} runs on GPU {choices}."]

    def card(self, preset, gpus) -> CardSetup:
        setup = preset.cards.get(card_key(gpus))
        if setup is None:
            raise ValueError(self.check_gpus(preset, gpus)[0])
        return setup

    def estimate(self, runtime, preset, values, gpus):
        setup = self.card(preset, gpus)
        ram = setup.estimate.ram_gib
        if setup.engine == "basalt":
            budget = values.get("resident_budget_gib")
            ram += budget if isinstance(budget, int) else 0
        if values.get("vision") not in (None, "off"):
            ram += 1  # the picture reader's pinned RAM
        return ram, {i: setup.estimate.gpu_min_free_gib[i] for i in gpus if i in setup.estimate.gpu_min_free_gib}

    def chat_sampling(self, preset, gpus) -> dict:
        setup = preset.cards.get(card_key(gpus))
        return dict(setup.sampling) if setup else {}

    def chat_thinking(self, preset, gpus):
        setup = preset.cards.get(card_key(gpus))
        if setup is None:
            return None
        levels = list(setup.thinking_levels)
        default = setup.thinking_default or (levels[-1] if levels else None)
        return {"levels": levels, "default": default, "off": setup.thinking_off and bool(levels)}

    # ----- launch -----------------------------------------------------------------------

    def launch(self, runtime, preset, values, gpus, base_env, launch_dir: Path):
        setup = self.card(preset, gpus)
        env = dict(base_env)
        env.update(setup.env)
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        if setup.path_prepend:
            env["PATH"] = ";".join(setup.path_prepend + [env.get("PATH", "")])
        if setup.engine == "basalt":
            config = self.basalt_config(runtime, setup, values, gpus)
            path = Path(launch_dir) / "basalt-config.json"
            return LaunchSpec(argv=[setup.executable, "serve", "--config", str(path)], env=env, cwd=setup.working_dir,
                              files={"basalt-config.json": json.dumps(config, indent=2)})
        config = self.strata_config(runtime, setup, values, gpus, Path(launch_dir))
        path = Path(launch_dir) / "strata-config.json"
        server = [str(WORKERS_DIR / "strata_inkling_thinking.py"), setup.server_dir] if setup.inkling_thinking \
            else [str(Path(setup.server_dir) / "serve" / "server.py")]
        argv = [setup.python, *server, "--engine", "strata",
                "--config", str(path), "--port", str(runtime.port), "--host", "127.0.0.1",
                "--gpu", card_key(gpus), "--parallel", "1", "--no-api-key", "--tokenizer", setup.tokenizer]
        return LaunchSpec(argv=argv, env=env, cwd=setup.server_dir,
                          files={"strata-config.json": json.dumps(config, indent=2)})

    @staticmethod
    def basalt_config(runtime, setup: CardSetup, values: dict, gpus) -> dict:
        entry = {"alias": setup.alias, "model": setup.model_path, "gpu": card_key(gpus)}
        entry.update(setup.fixed)
        for key, value in values.items():
            if value is None:
                continue
            if key == "vision":
                entry["vision"] = BASALT_VISION.get(value, "off")
            elif key in BASALT_KEYS:
                entry[BASALT_KEYS[key]] = value
        return {"version": 2, "server": {"host": "127.0.0.1", "port": runtime.port}, "models": [entry]}

    @staticmethod
    def strata_config(runtime, setup: CardSetup, values: dict, gpus, launch_dir: Path) -> dict:
        args = ["--native", setup.pack]
        if values.get("max_context"):
            args += ["--max-context", str(values["max_context"])]
        if values.get("vision") not in (None, "off") and setup.vision_pack:
            args += ["--vision", setup.vision_pack]
        if values.get("kv"):
            args += ["--kv", str(values["kv"])]
        if values.get("vram_reserve_mib") is not None:
            args += ["--vram-reserve-mib", str(values["vram_reserve_mib"])]
        if setup.drafter:
            args += ["--draft", setup.drafter]
        return {"exe": setup.component, "args": args, "cwd": setup.server_dir, "tokenizer": setup.tokenizer,
                "model_name": setup.model_name, "arch": setup.arch, "log": str(launch_dir / "engine.log"),
                "lib_dirs": [], "port": runtime.port, "parallel": 1, "gpu": card_indices(card_key(gpus))[0],
                "drafting": setup.drafter or "off"}

    # ----- readiness ----------------------------------------------------------------------

    def probe(self, runtime):
        """Basalt lists its models with a status; Strata's /health says whether the model is loaded."""
        base = f"http://127.0.0.1:{runtime.port}"
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as response:
                health = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError):
            health = None
        if isinstance(health, dict) and health.get("service") == "strata":
            return "loaded" if health.get("loaded") is True else "loading"
        try:
            with urllib.request.urlopen(base + "/v1/models", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        statuses = set()
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            for key in ("status", "state"):
                value = item.get(key) if isinstance(item, dict) else None
                if isinstance(value, dict):
                    value = value.get("value")
                if isinstance(value, str):
                    statuses.add(value)
        if "loaded" in statuses:
            return "loaded"
        if "failed" in statuses:
            return "failed"
        return "loading"
