"""TextModelBroker: worker jobs that ask for a text model get one; a model started for them is stopped afterwards."""
import time
from types import SimpleNamespace

import pytest

from generationstation import text_models
from generationstation.text_models import TextModelBroker


class Plugin:
    def __init__(self, chat=False, asks=False):
        self.chats, self.text_model_jobs, self.records = chat, asks, {}

    def job_status(self, runtime, job_id):
        return self.records.get(job_id)

    def chat_sampling(self, preset, gpus):
        return {"temperature": 1.0} if gpus == [1] else {}


class Catalog:
    def __init__(self):
        preset = SimpleNamespace(gpus=[0])
        self.runtimes = {
            "meeting": SimpleNamespace(name="Meeting notes", port=8230, default_text_model="flash_next",
                                       no_correction_models=["inkling2"], presets={}, default_preset=None),
            "flash_next": SimpleNamespace(name="Qwen3.8 Flash-Next", port=8162, presets={"main": preset}, default_preset="main"),
            "inkling2": SimpleNamespace(name="Inkling 2 Mini", port=8161, presets={"main": preset}, default_preset="main"),
        }
        self.plugins = {"meeting": Plugin(asks=True), "flash_next": Plugin(chat=True), "inkling2": Plugin(chat=True)}

    def plugin(self, model_id):
        return self.plugins[model_id]


class Store:
    def __init__(self, states, jobs):
        self.states, self.jobs, self.launches = states, jobs, {}

    def runtime_states(self):
        return {k: {"state": v} for k, v in self.states.items()}

    def list_jobs(self, model_id, limit):
        return [j for j in self.jobs if j["model_id"] == model_id]

    def latest_launches(self):
        return self.launches


class Tools:
    """HostTools stand-in: starts succeed unless refused; the card names follow the desktop's."""
    def __init__(self, store, refuse=()):
        self.store, self.refuse, self.calls = store, set(refuse), []

    def snapshot(self):
        return {}

    def _cards(self, host):
        return {0: {"name": "NVIDIA GeForce RTX 5090"}, 1: {"name": "NVIDIA GeForce RTX 4080"}}

    def start(self, args):
        self.calls.append(("start", args))
        if args.get("card") in self.refuse or args["model_id"] in self.refuse:
            return {"text": "Not started: it would not fit.", "note": "won't fit"}
        self.store.states[args["model_id"]] = "ready"
        self.store.launches[args["model_id"]] = {"launch": {"preset": "main", "gpus": [0] if args.get("card") == "RTX 5090" else [0, 1]}}
        return {"text": "running", "note": "started"}

    def stop(self, args):
        self.calls.append(("stop", args))
        self.store.states[args["model_id"]] = "unloaded"
        return {"text": "stopped", "note": f"Stopped {args['model_id']}"}


@pytest.fixture
def posted(monkeypatch):
    sent = []
    monkeypatch.setattr(text_models, "_post", lambda port, job_id, value: sent.append((port, job_id, value)) or (200, {}))
    return sent


def broker_for(states, request, refuse=()):
    catalog = Catalog()
    store = Store(states, [{"id": "job-1", "model_id": "meeting", "status": "running"}])
    catalog.plugins["meeting"].records["job-1"] = {"status": "running", "details": {"needs": {"text_model": request}}}
    tools = Tools(store, refuse)
    broker = TextModelBroker(store, catalog, tools, chat=None, log=lambda *_: None)
    return broker, catalog, store, tools


def settle(broker):
    broker.tick()
    deadline = time.time() + 5
    while broker.handling and time.time() < deadline:
        time.sleep(0.02)


def test_a_running_text_model_is_handed_over_without_starting_anything(posted):
    broker, catalog, store, tools = broker_for({"meeting": "ready", "inkling2": "ready"}, {"model": "auto", "gpu": 1})
    store.launches["inkling2"] = {"launch": {"preset": "main", "gpus": [1]}}
    settle(broker)
    port, job_id, value = posted[0]
    assert (port, job_id) == (8230, "job-1") and tools.calls == []
    assert value["base_url"] == "http://127.0.0.1:8161" and value["model_id"] == "inkling2"
    assert value["can_correct"] is False and value["sampling"] == {"temperature": 1.0}


def test_none_running_starts_the_default_on_the_jobs_card_then_stops_it_when_the_job_ends(posted):
    broker, catalog, store, tools = broker_for({"meeting": "ready"}, {"model": "auto", "gpu": 0})
    settle(broker)
    assert tools.calls == [("start", {"model_id": "flash_next", "card": "RTX 5090"})]
    assert posted[0][2]["base_url"] == "http://127.0.0.1:8162" and posted[0][2]["can_correct"] is True
    catalog.plugins["meeting"].records["job-1"] = {"status": "running", "details": {}}
    settle(broker)
    assert ("stop", {"model_id": "flash_next"}) not in tools.calls  # still in use by the running job
    catalog.plugins["meeting"].records["job-1"] = {"status": "done", "details": {}}
    settle(broker)
    assert tools.calls[-1] == ("stop", {"model_id": "flash_next"}) and store.states["flash_next"] == "unloaded"


def test_a_model_that_does_not_fit_the_jobs_card_tries_its_usual_cards(posted):
    broker, catalog, store, tools = broker_for({"meeting": "ready"}, {"model": "flash_next", "gpu": 1}, refuse={"RTX 4080"})
    settle(broker)
    assert [c[1] for c in tools.calls] == [{"model_id": "flash_next", "card": "RTX 4080"}, {"model_id": "flash_next"}]
    assert posted[0][2]["model_id"] == "flash_next"


def test_a_refused_start_answers_the_job_with_the_reason(posted):
    broker, catalog, store, tools = broker_for({"meeting": "ready"}, {"model": "flash_next", "gpu": 0}, refuse={"flash_next"})
    settle(broker)
    assert posted[0][2] == {"error": "Not started: it would not fit."}
    assert broker.started == {}


def test_an_unknown_model_is_refused_and_a_model_already_running_is_never_stopped(posted):
    broker, catalog, store, tools = broker_for({"meeting": "ready", "flash_next": "ready"}, {"model": "nope"})
    settle(broker)
    assert posted[0][2] == {"error": "There is no text model 'nope'."}
    catalog.plugins["meeting"].records["job-1"] = {"status": "running", "details": {"needs": {"text_model": {"model": "flash_next"}}}}
    settle(broker)
    catalog.plugins["meeting"].records["job-1"] = {"status": "done", "details": {}}
    settle(broker)
    assert tools.calls == []  # it was running before the job asked; the broker leaves it alone
