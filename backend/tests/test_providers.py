"""Hosted chat models: the optional providers in the runtimes file, the person's choice of models, OpenCode's config, and the chat
using a hosted model (no network: the gateway is a stand-in)."""
import io
import json
import urllib.error

import pytest

from generationstation.chat import ChatManager
from generationstation.providers import ProviderConfig, ProviderRegistry
from generationstation.runtimes import CatalogError, parse_catalog
from generationstation.uploads import UploadStore
from tests.test_chat import Generation, Store, catalog, follow

MODELS = {"data": [{"id": "claude-sonnet-5-5", "mode": "chat"}, {"id": "claude-haiku-5-5", "mode": "chat"}, {"id": "claude-opus-4-5", "mode": "chat"},
                   {"id": "text-embedding-3", "mode": "embedding"}, {"id": "no-mode-model"}]}


class Gateway:
    """Stands in for LiteLLM: /v1/models, and one canned chat stream per request (kept, with its URL and headers)."""
    def __init__(self, status=200):
        self.status, self.listed, self.chats = status, 0, []

    def __call__(self, request, timeout=None):
        if request.full_url.endswith("/models"):
            self.listed += 1
            if self.status != 200:
                raise urllib.error.HTTPError(request.full_url, self.status, "no", {}, io.BytesIO(b"{}"))
            return io.BytesIO(json.dumps(MODELS).encode())
        self.chats.append((request.full_url, dict(request.header_items()), json.loads(request.data)))
        line = f"data: {json.dumps({'choices': [{'delta': {'content': 'Hello from Claude.'}, 'finish_reason': 'stop'}]})}\n\ndata: [DONE]\n\n"
        return io.BytesIO(line.encode())


def registry(tmp_path, gateway=None, environ=None, **config):
    configs = {"litellm": ProviderConfig(name="LiteLLM", base_url="https://gateway.example/", api_key_env="GATEWAY_TOKEN", **config)}
    return ProviderRegistry(configs, tmp_path / "providers.json", opener=gateway or Gateway(), environ={"GATEWAY_TOKEN": "secret"} if environ is None else environ)


def test_a_provider_needs_an_address_and_a_token_variable():
    with pytest.raises(ValueError, match="base_url and api_key_env"):
        ProviderConfig(name="X", base_url="https://x")
    with pytest.raises(CatalogError, match="Invalid provider id"):
        parse_catalog({"runtimes": {}, "providers": {"Bad Id": {"name": "X", "base_url": "https://x", "api_key_env": "T"}}})
    assert set(parse_catalog({"runtimes": {}, "providers": {"litellm": {"name": "X", "base_url": "https://x", "api_key_env": "T"}}}).providers) == {"litellm"}


def test_the_models_listed_are_chat_models_sorted_and_the_list_is_kept_for_a_while(tmp_path):
    gateway = Gateway()
    reg = registry(tmp_path, gateway)
    models, error = reg.models("litellm")
    assert error is None and [m["id"] for m in models] == ["claude-haiku-5-5", "claude-opus-4-5", "claude-sonnet-5-5", "no-mode-model"]
    reg.models("litellm")
    assert gateway.listed == 1
    reg.models("litellm", refresh=True)
    assert gateway.listed == 2


def test_nothing_is_offered_until_chosen_unless_include_patterns_say_otherwise(tmp_path):
    assert registry(tmp_path).hosted_ids() == []
    reg = registry(tmp_path, include=["claude-*-5-5"])
    assert reg.hosted_ids() == ["litellm:claude-haiku-5-5", "litellm:claude-sonnet-5-5"]
    reg.set_enabled("litellm", ["claude-opus-4-5"])  # the person's choice replaces the defaults
    assert reg.hosted_ids() == ["litellm:claude-opus-4-5"]
    assert ProviderRegistry(reg.configs, tmp_path / "providers.json", opener=Gateway(), environ={}).hosted_ids() == ["litellm:claude-opus-4-5"]  # and is kept
    with pytest.raises(ValueError, match="does not list"):
        reg.set_enabled("litellm", ["claude-nonexistent-9"])
    with pytest.raises(ValueError, match="Choose a list"):
        reg.set_enabled("litellm", "claude-opus-4-5")


def test_the_description_says_what_is_listed_what_is_on_and_why_a_lookup_failed(tmp_path):
    reg = registry(tmp_path, include=["claude-sonnet-5-5"])
    (provider,) = reg.describe()
    assert provider["name"] == "LiteLLM" and provider["token_set"] and provider["error"] is None
    assert [(m["id"], m["enabled"]) for m in provider["models"]][:3] == [("claude-haiku-5-5", False), ("claude-opus-4-5", False), ("claude-sonnet-5-5", True)]
    assert "secret" not in json.dumps(provider)
    (down,) = registry(tmp_path, Gateway(status=401)).describe()
    assert down["models"] == [] and "401" in down["error"] and "token" in down["error"]
    (unset,) = registry(tmp_path, environ={}).describe()
    assert not unset["token_set"] and "GATEWAY_TOKEN" in unset["error"]


def test_a_hosted_target_names_where_to_send_and_refuses_without_the_token(tmp_path):
    reg = registry(tmp_path, include=["claude-sonnet-5-5"])
    target = reg.target("litellm:claude-sonnet-5-5")
    assert (target.url, target.model, target.headers()) == ("https://gateway.example/v1/chat/completions", "claude-sonnet-5-5", {"Authorization": "Bearer secret"})
    assert reg.target("litellm:claude-haiku-5-5") is None and reg.target("other:claude-sonnet-5-5") is None and reg.target("basalt") is None
    reg.environ.pop("GATEWAY_TOKEN")  # the token goes after the model list was fetched
    with pytest.raises(RuntimeError, match="GATEWAY_TOKEN"):
        reg.target("litellm:claude-sonnet-5-5").headers()


def chat(tmp_path, gateway, **config):
    store = Store()
    reg = registry(tmp_path, gateway, include=["claude-sonnet-5-5"], **config)
    return store, ChatManager(store, catalog(tmp_path), Generation(store, tmp_path / "jobs"), UploadStore(tmp_path / "runtime"), opener=gateway, providers=reg)


def test_a_conversation_on_a_hosted_model_goes_to_the_gateway_with_the_token_and_without_the_local_only_fields(tmp_path):
    gateway = Gateway()
    store, manager = chat(tmp_path, gateway)
    conversation = manager.create(model_id="litellm:claude-sonnet-5-5")
    assert conversation["model_id"] == "litellm:claude-sonnet-5-5"
    events = follow(manager.start(conversation["id"], "Hi", [], thinking="high"))
    assert [d for e, d in events if e == "delta"] == [{"content": "Hello from Claude."}]
    url, headers, body = gateway.chats[0]
    assert url == "https://gateway.example/v1/chat/completions" and headers["Authorization"] == "Bearer secret"
    assert body["model"] == "claude-sonnet-5-5" and body["reasoning_effort"] == "high" and "enable_thinking" not in body
    follow(manager.start(conversation["id"], "Again", [], thinking="off"))
    _, _, body = gateway.chats[1]
    assert "reasoning_effort" not in body and "enable_thinking" not in body
    assert manager.thinking_for("litellm:claude-sonnet-5-5")["levels"] == ["low", "medium", "high"]
    assert store.messages[-1]["content"] == "Hello from Claude."


def test_the_chat_can_move_to_a_hosted_model_but_not_an_unchosen_one_and_the_assistant_stays_local(tmp_path):
    gateway = Gateway()
    store, manager = chat(tmp_path, gateway)
    with pytest.raises(Exception, match="does not chat"):
        manager.create(model_id="litellm:claude-haiku-5-5")
    local = manager.create(model_id="basalt")
    follow(manager.start(local["id"], "Hi", [], thinking=None, model_id="litellm:claude-sonnet-5-5"))
    assert store.conversations[local["id"]]["model_id"] == "litellm:claude-sonnet-5-5"
    assert manager.assistant_model() == "basalt"


def test_a_missing_token_is_a_message_in_the_conversation_not_a_crash(tmp_path):
    gateway = Gateway()
    store = Store()
    reg = registry(tmp_path, gateway, include=["claude-sonnet-5-5"])
    manager = ChatManager(store, catalog(tmp_path), Generation(store, tmp_path / "jobs"), UploadStore(tmp_path / "runtime"), opener=gateway, providers=reg)
    conversation = manager.create(model_id="litellm:claude-sonnet-5-5")
    reg.environ.pop("GATEWAY_TOKEN")
    events = follow(manager.start(conversation["id"], "Hi", []))
    assert any(e == "message" and d["status"] == "error" and "GATEWAY_TOKEN" in d["error_message"] for e, d in events)
    assert gateway.chats == []


def test_the_endpoints_list_choose_and_refresh_without_the_token_in_view(tmp_path):
    from fastapi.testclient import TestClient

    from generationstation.app import create_app
    from tests.test_app import TOKEN, FakeMonitor, FakeStore, settings

    runtimes = tmp_path / "runtimes.json"
    runtimes.write_text(json.dumps({"runtimes": {}, "providers": {"work": {"name": "Work", "base_url": "https://gw.example", "api_key_env": "WORK_TOKEN"}}}))
    app = create_app(settings=settings(runtime_dir=tmp_path / "runtime", runtimes_file=runtimes), store=FakeStore(), monitor=FakeMonitor())
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        assert client.get("/api/providers", headers=headers).json()["providers"][0]["name"] == "Work"
        assert client.put("/api/providers/other/models", json={"enabled": []}, headers=headers).status_code == 404
        assert client.post("/api/providers/other/refresh", headers=headers).status_code == 404
        assert client.get("/api/providers").status_code == 401


def test_a_token_is_found_in_the_environment_or_the_env_file_and_nowhere_else(tmp_path):
    from generationstation.providers import EnvFileEnviron

    env_file = tmp_path / ".env"
    env_file.write_text("GATEWAY_TOKEN=from-file\nOTHER=1\n")
    assert EnvFileEnviron(env_file, {}).get("GATEWAY_TOKEN") == "from-file"
    assert EnvFileEnviron(env_file, {"GATEWAY_TOKEN": "from-env"}).get("GATEWAY_TOKEN") == "from-env"  # the environment first
    assert EnvFileEnviron(env_file, {}).get("MISSING") is None and EnvFileEnviron(tmp_path / "none.env", {}).get("GATEWAY_TOKEN") is None
    env_file.write_text("GATEWAY_TOKEN=changed\n")
    assert EnvFileEnviron(env_file, {}).get("GATEWAY_TOKEN") == "changed"  # read each time: no restart needed


def test_providers_set_up_in_the_settings_replace_the_files_and_are_checked_and_tested(tmp_path):
    kept = {}
    reg = ProviderRegistry({"litellm": ProviderConfig(name="From file", base_url="https://old.example", api_key_env="OLD")}, tmp_path / "p.json",
                           opener=Gateway(), environ={"GATEWAY_TOKEN": "secret"}, saved=lambda: kept, save=lambda data: kept.update(data) if data else kept.clear())
    assert [(p["id"], p["origin"]) for p in reg.configured()] == [("litellm", "file")]
    done = reg.set_configs([{"name": "Work gateway", "base_url": "https://gateway.example", "api_key_env": "GATEWAY_TOKEN"},
                            {"id": "litellm", "name": "LiteLLM", "base_url": "https://gateway.example", "api_key_env": "GATEWAY_TOKEN"}])
    assert sorted((p["id"], p["origin"]) for p in done) == [("litellm", "settings"), ("work-gateway", "settings")]
    assert reg.configs["litellm"].name == "LiteLLM"  # the setting takes the file's place
    assert "secret" not in json.dumps(kept)  # only the variable's name is kept
    for bad, text in (([{"name": "X", "base_url": "https://x"}], "api_key_env"), 
                      ([{"name": "A", "base_url": "https://x", "api_key_env": "T"}, {"name": "A", "base_url": "https://y", "api_key_env": "T"}], "Two providers"),
                      ("nope", "list")):
        with pytest.raises(ValueError, match=text):
            reg.set_configs(bad)
    assert reg.test({"name": "T", "base_url": "https://gateway.example", "api_key_env": "GATEWAY_TOKEN"})[0] is True
    ok, message = reg.test({"name": "T", "base_url": "https://gateway.example", "api_key_env": "UNSET_VARIABLE"})
    assert not ok and "UNSET_VARIABLE" in message
    assert reg.test({"name": "T"})[0] is False
    reg.set_configs([])
    assert [p["origin"] for p in reg.configured()] == ["file"]


def test_the_settings_endpoints_save_test_and_list_providers(tmp_path):
    from fastapi.testclient import TestClient

    from generationstation.app import create_app
    from tests.test_app import TOKEN, FakeMonitor, FakeStore, settings

    class Store(FakeStore):
        def __init__(self):
            super().__init__()
            self.kept = {}

        def get_setting(self, key, default=None):
            return self.kept.get(key, default)

        def set_setting(self, key, value):
            self.kept[key] = value

    store = Store()
    app = create_app(settings=settings(runtime_dir=tmp_path / "runtime", runtimes_file=None), store=store, monitor=FakeMonitor())
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        assert client.get("/api/providers/config", headers=headers).json() == {"providers": []}
        body = {"providers": [{"name": "Work gateway", "base_url": "https://gateway.example", "api_key_env": "GATEWAY_TOKEN"}]}
        done = client.put("/api/providers/config", json=body, headers=headers)
        assert done.status_code == 200 and done.json()["providers"][0]["id"] == "work-gateway" and done.json()["providers"][0]["origin"] == "settings"
        assert "work-gateway" in store.kept["hosted_providers"]
        assert client.get("/api/providers", headers=headers).json()["providers"][0]["name"] == "Work gateway"
        assert client.put("/api/providers/config", json={"providers": [{"name": "X"}]}, headers=headers).status_code == 422
        assert client.put("/api/providers/config", json={"providers": [{"name": "X", "token": "no"}]}, headers=headers).status_code == 422
        unset = client.post("/api/providers/test", json={"name": "T", "base_url": "https://gateway.example", "api_key_env": "SURELY_UNSET_VARIABLE"}, headers=headers)
        assert unset.status_code == 200 and unset.json()["ok"] is False and "SURELY_UNSET_VARIABLE" in unset.json()["message"]


def test_the_assistant_uses_a_running_local_model_first_then_a_hosted_one(tmp_path):
    store = Store()
    gateway = Gateway()
    reg = registry(tmp_path, gateway, include=["claude-haiku-5-5"])
    manager = ChatManager(store, catalog(tmp_path), Generation(store, tmp_path / "jobs"), UploadStore(tmp_path / "runtime"), opener=gateway, providers=reg)
    store.states = {}
    assert manager.assistant_model() == "litellm:claude-haiku-5-5"  # nothing local runs
    assert manager.assistant(fresh=True)["conversation"]["model_id"] == "litellm:claude-haiku-5-5"
    store.states = {"basalt": {"state": "ready"}}
    assert manager.assistant_model() == "basalt"
