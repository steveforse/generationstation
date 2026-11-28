"""Hosted chat models: an OpenAI-compatible gateway (LiteLLM in front of Bedrock, for one) that the chat can use next to the local models.

A provider is set up in the runtimes file under "providers" and is optional. Its models are not started or stopped and use no memory
on this computer; they are listed from the gateway's `/v1/models` and the person chooses which of them
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

from dotenv import dotenv_values
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
    # Glob patterns of model ids that are on until the person chooses otherwise (for example "claude-*-5-5").
    include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def complete(self):
        if not (self.base_url and self.api_key_env):
            raise ValueError("a provider needs base_url and api_key_env")
        return self


class EnvFileEnviron:
    """Where a token's variable is looked up: the process environment, then the host's .env file (read each time, so a change to the
    file needs no restart). Only `get` is used."""

    def __init__(self, env_file=None, environ=None):
        self.env_file, self.environ = Path(env_file) if env_file else None, os.environ if environ is None else environ

    def get(self, name, default=None):
        if self.environ.get(name):
            return self.environ.get(name)
        if self.env_file and self.env_file.is_file():
            try:
                return dotenv_values(self.env_file).get(name) or default
            except OSError:
                return default
        return default


def provider_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-")
    return slug if PROVIDER_ID.fullmatch(slug or "") else "provider"


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
    def __init__(self, configs, state_file, opener=None, environ=None, saved=None, save=None):
        # `configs` are the providers of the runtimes file; `saved` and `save` read and write the ones set up on the Host settings page
        # (a dict of id -> config fields), which take the place of a file provider with the same id.
        self.file_configs = {key: value for key, value in (configs or {}).items()}
        self._saved, self._save = saved or dict, save
        self.state_file = Path(state_file)
        self.opener = opener or urllib.request.urlopen
        self.environ = environ if environ is not None else os.environ
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[float, list[dict], str | None]] = {}

    # ----- settings -----------------------------------------------------------------------------

    @property
    def configs(self):
        out = dict(self.file_configs)
        for key, fields in (self._saved() or {}).items():
            try:
                out[key] = ProviderConfig(**{name: value for name, value in fields.items() if name in ProviderConfig.model_fields})
            except (ValueError, TypeError):
                continue
        return out

    def configured(self):
        """The providers as set up, with where each came from ("settings" can be edited, "file" is the runtimes file's)."""
        saved = set((self._saved() or {}).keys())
        return [{"id": key, "origin": "settings" if key in saved else "file", **config.model_dump(exclude={"include"}, exclude_none=True)} for key, config in self.configs.items()]

    def set_configs(self, items):
        """Replace the providers set up on the Host settings page. Raises ValueError saying what is wrong."""
        if not isinstance(items, list) or len(items) > 10:
            raise ValueError("Give a list of up to 10 providers.")
        out = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each provider needs a name and an address.")  # noqa: TRY004
            fields = {key: value for key, value in item.items() if key in ProviderConfig.model_fields and key != "include" and value not in (None, "")}
            try:
                config = ProviderConfig(**fields)
            except ValueError as exc:
                problems = exc.errors() if hasattr(exc, "errors") else []
                raise ValueError((problems[0]["msg"].removeprefix("Value error, ") if problems else str(exc)) + f" ({fields.get('name', 'a provider')})") from exc
            key = item.get("id") or provider_slug(config.name)
            if not isinstance(key, str) or not PROVIDER_ID.fullmatch(key):
                raise ValueError(f"{config.name} has an invalid id.")
            if key in out:
                raise ValueError(f"Two providers are called {config.name}.")
            out[key] = config.model_dump(exclude={"include"}, exclude_none=True)
        if self._save is None:
            raise ValueError("Providers cannot be saved on this host.")
        self._save(out)
        with self.lock:
            self.cache.clear()
        return self.configured()

    def test(self, item):
        """Try one provider (as typed, not saved): (ok, message) in plain words."""
        try:
            config = ProviderConfig(**{key: value for key, value in (item or {}).items() if key in ProviderConfig.model_fields and key != "include" and value not in (None, "")})
        except ValueError as exc:
            problems = exc.errors() if hasattr(exc, "errors") else []
            return False, problems[0]["msg"].removeprefix("Value error, ") if problems else str(exc)
        models, error = self._list(config)
        if error:
            return False, error
        if not models:
            return False, "It answered, but lists no chat models."
        return True, f"Works: {len(models)} chat models, such as {', '.join(item['id'] for item in models[:3])}."

    def _resolve(self, provider_id):
        return self._resolve_config(self.configs[provider_id])

    def _resolve_config(self, config):
        """(base_url, key_env) of a provider."""
        return config.base_url.rstrip("/"), config.api_key_env

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
        if provider_id not in self.configs:
            return [], "That provider is not set up."
        models, error = self._list(self.configs[provider_id])
        with self.lock:
            self.cache[provider_id] = (time.time(), models, error)
        return models, error

    def _list(self, config):
        """([{id, name}], error) straight from the gateway."""
        models, error = [], None
        try:
            base, key_env = self._resolve_config(config)
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
            base, key_env = self._resolve(provider_id)
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
            base, key_env = self._resolve(provider_id)
        except ValueError:
            return None
        return HostedTarget(provider_id, self.configs[provider_id].name, model, self._api(base) + "/chat/completions", key_env, self.environ)
