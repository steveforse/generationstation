"""Hosted chat models: an OpenAI-compatible gateway (LiteLLM in front of Bedrock, for one) that the chat can use next to the local models.

A provider is set up in the runtimes file under "providers" and is optional. Its models are not started or stopped and use no memory
on this computer; they are listed from the gateway's `/v1/models` (or from OpenCode's own config) and the person chooses which of them
the chat offers. The token is never kept here: `api_key_env` names the environment variable that holds it, read when a request is made,
so it must be set where the backend is started.

A hosted model is addressed as "<provider id>:<model id>" wherever a local model's id would be (a conversation's model, the chat's picker).
"""
import fnmatch
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
CACHE_SECONDS = 300
ERROR_SECONDS = 30  # a failed lookup is tried again soon
MAX_SELECTED = 200
# What the chat offers for thinking on a hosted model: a level is sent as `reasoning_effort`, "off" sends nothing.
THINKING = {"levels": ["low", "medium", "high"], "default": "low", "off": True}


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    # The gateway's address (its OpenAI-style API is at <base_url>/v1) and the environment variable that holds its token.
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    # "gateway": list the models the gateway reports. "opencode": read the provider named `opencode_provider` from OpenCode's config
    # (`opencode_config`, default ~/.config/opencode/opencode.json) for the address, the token's variable and the model list;
    # anything given here wins over it.
    source: Literal["gateway", "opencode"] = "gateway"
    opencode_provider: str | None = None
    opencode_config: str | None = None
    # Glob patterns of model ids that are on until the person chooses otherwise (for example "claude-*-5-5").
    include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def complete(self):
        if self.source == "gateway" and not (self.base_url and self.api_key_env):
            raise ValueError("a gateway provider needs base_url and api_key_env")
        if self.source == "opencode" and not self.opencode_provider:
            raise ValueError("an opencode provider needs opencode_provider")
        return self


def _strip_jsonc(text):
    """OpenCode's config may be JSONC: comments and trailing commas out, string contents left alone."""
    out, i, in_string = [], 0, False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\":
                out.append(text[i + 1:i + 2])
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 1
        else:
            out.append(char)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def read_opencode(path, provider):
    """(base_url, api_key_env, models) of a provider in OpenCode's config; models is a {id: name} dict or None. Raises ValueError."""
    config = Path(path or "~/.config/opencode/opencode.json").expanduser()
    try:
        data = json.loads(_strip_jsonc(config.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ValueError(f"OpenCode's config {config} could not be read ({exc.__class__.__name__}).") from exc
    entry = (data.get("provider") or {}).get(provider)
    if not isinstance(entry, dict):
        raise ValueError(f"OpenCode's config has no provider named {provider}.")  # noqa: TRY004
    options = entry.get("options") or {}
    key = options.get("apiKey") or ""
    found = re.fullmatch(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}", key) if isinstance(key, str) else None
    models = entry.get("models")
    names = {mid: (spec.get("name") if isinstance(spec, dict) and spec.get("name") else mid) for mid, spec in models.items()} if isinstance(models, dict) and models else None
    return options.get("baseURL"), (found.group(1) if found else None), names


class HostedTarget:
    """Where to send one hosted model's chat requests."""

    def __init__(self, provider_id, provider_name, model, url, key_env, environ):
        self.provider_id, self.provider_name, self.model, self.url, self.key_env, self.environ = provider_id, provider_name, model, url, key_env, environ
        self.name = model

    def headers(self):
        key = self.environ.get(self.key_env or "", "")
        if not key:
            raise RuntimeError(f"{self.provider_name} needs the environment variable {self.key_env} where the backend is started.")
        return {"Authorization": f"Bearer {key}"}


class ProviderRegistry:
    def __init__(self, configs, state_file, opener=None, environ=None):
        self.configs = {key: value for key, value in (configs or {}).items()}
        self.state_file = Path(state_file)
        self.opener = opener or urllib.request.urlopen
        self.environ = environ if environ is not None else os.environ
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[float, list[dict], str | None]] = {}

    # ----- settings -----------------------------------------------------------------------------

    def _resolve(self, provider_id):
        """(base_url, key_env, {id: name} or None) for a provider, from its config and OpenCode's."""
        config = self.configs[provider_id]
        base, key_env, names = config.base_url, config.api_key_env, None
        if config.source == "opencode":
            found_base, found_key, names = read_opencode(config.opencode_config, config.opencode_provider)
            base, key_env = base or found_base, key_env or found_key
        if not base:
            raise ValueError(f"{config.name} has no address (base_url).")
        return base.rstrip("/"), key_env, names

    @staticmethod
    def _api(base):
        return base if base.endswith("/v1") else base + "/v1"

    def _selection(self):
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    # ----- models -------------------------------------------------------------------------------

    def models(self, provider_id, refresh=False):
        """([{id, name}], error) for a provider, from its cache unless it is older than five minutes or `refresh`."""
        with self.lock:
            cached = self.cache.get(provider_id)
        if cached and not refresh and time.time() - cached[0] < (ERROR_SECONDS if cached[2] else CACHE_SECONDS):
            return cached[1], cached[2]
        models, error = [], None
        try:
            base, key_env, names = self._resolve(provider_id)
            if names:
                models = [{"id": mid, "name": name} for mid, name in names.items()]
            else:
                request = urllib.request.Request(self._api(base) + "/models", headers=self._auth(key_env))
                with self.opener(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
                models = sorted(({"id": item["id"], "name": item["id"]} for item in payload.get("data") or []
                                 if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("mode") in (None, "chat")), key=lambda item: item["id"])
        except ValueError as exc:
            error = str(exc)
        except urllib.error.HTTPError as exc:
            error = f"The gateway answered {exc.code}." + (" Check the token." if exc.code in (401, 403) else "")
        except (urllib.error.URLError, OSError, KeyError, AttributeError):
            error = "The gateway could not be reached."
        except RuntimeError as exc:
            error = str(exc)
        with self.lock:
            self.cache[provider_id] = (time.time(), models, error)
        return models, error

    def _auth(self, key_env):
        key = self.environ.get(key_env or "", "")
        if not key:
            raise RuntimeError(f"The environment variable {key_env} is not set where the backend is started.")
        return {"Authorization": f"Bearer {key}"}

    def enabled(self, provider_id, fetch=False):
        """The model ids the chat offers for a provider: the person's choice, else the models matching `include` (looked up if `fetch`)."""
        saved = self._selection().get(provider_id)
        if isinstance(saved, list):
            return [item for item in saved if isinstance(item, str)]
        config = self.configs[provider_id]
        if not config.include:
            return []
        cached = self.cache.get(provider_id)
        models = cached[1] if cached else (self.models(provider_id)[0] if fetch else [])
        return [item["id"] for item in models if any(fnmatch.fnmatchcase(item["id"], pattern) for pattern in config.include)]

    def set_enabled(self, provider_id, ids):
        models, _ = self.models(provider_id)
        known = {item["id"] for item in models}
        if not isinstance(ids, list) or len(ids) > MAX_SELECTED or any(not isinstance(item, str) for item in ids):
            raise ValueError("Choose a list of model ids.")
        unknown = [item for item in ids if known and item not in known]
        if unknown:
            raise ValueError(f"The gateway does not list {', '.join(unknown[:3])}.")
        with self.lock:
            data = self._selection()
            data[provider_id] = sorted(set(ids))
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_file.with_suffix(".tmp")
            temp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            temp.replace(self.state_file)

    # ----- what the API and the chat use ----------------------------------------------------------

    def describe(self, refresh=False):
        out = []
        for provider_id, config in self.configs.items():
            models, error = self.models(provider_id, refresh)
            on = set(self.enabled(provider_id, fetch=True))
            try:
                base, key_env, _ = self._resolve(provider_id)
            except ValueError:
                base, key_env = config.base_url, config.api_key_env
            out.append({"id": provider_id, "name": config.name, "address": base, "token_variable": key_env,
                        "token_set": bool(self.environ.get(key_env or "")), "error": error,
                        "models": [{"id": item["id"], "name": item["name"], "enabled": item["id"] in on} for item in models]
                        + [{"id": item, "name": item, "enabled": True} for item in sorted(on - {m["id"] for m in models})]})
        return out

    def hosted_ids(self):
        """"<provider>:<model>" for every model the chat offers (a lookup the first time and then every five minutes)."""
        return [f"{provider_id}:{model}" for provider_id in self.configs for model in self.enabled(provider_id, fetch=True)]

    def target(self, key):
        """The HostedTarget of an offered hosted model, or None."""
        provider_id, _, model = (key or "").partition(":")
        if provider_id not in self.configs or model not in self.enabled(provider_id, fetch=True):
            return None
        try:
            base, key_env, _ = self._resolve(provider_id)
        except ValueError:
            return None
        return HostedTarget(provider_id, self.configs[provider_id].name, model, self._api(base) + "/chat/completions", key_env, self.environ)
