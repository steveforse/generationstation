"""The chat's host and web tools, with a stand-in lifecycle and stand-in web (nothing starts, nothing goes online)."""
import io
import json
import os
import threading
import urllib.error
from datetime import datetime, timedelta, timezone
from email.message import Message

import pytest

from generationstation.chat import ChatManager
from generationstation.chat_tools import HostTools, JobTools, WebTools, public_url
from generationstation.lifecycle import LifecycleError
from generationstation.logs import LogStore
from generationstation.uploads import UploadStore
from tests.test_chat import Generation, Server, Store, catalog, follow

GIB = 1024**3
G5090, G4080 = "GPU-5090", "GPU-4080"


class Lifecycle:
    class settings:
        ram_headroom_bytes = 4 * GIB
        gpu_headroom_bytes = 2 * GIB

    def __init__(self, store, need_gpu_gib=8, outcome="ready"):
        self.store, self.need_gpu_gib, self.outcome = store, need_gpu_gib, outcome
        self.started, self.stopped, self.ops = [], [], {}

    def estimate_runtime(self, model_id, preset_key, overrides, gpus, host):
        ids = {0: G5090, 1: G4080}
        return {"ram_bytes": 6 * GIB, "gpu_vram_bytes_by_id": {ids[g]: self.need_gpu_gib * GIB for g in gpus},
                "ram_headroom_bytes": 4 * GIB, "gpu_headroom_bytes": 2 * GIB, "reserved_ram_bytes": 0,
                "reserved_gpu_vram_bytes_by_id": {}}

    def create_runtime_load(self, model_id, preset_key, overrides, gpus, key, host):
        self.started.append((model_id, preset_key, gpus))
        self.ops["s"] = {"id": "s", "status": self.outcome, "error_message": "worker exited" if self.outcome == "failed" else None}
        if self.outcome == "ready":
            self.store.states[model_id] = {"state": "ready"}
        return {"id": "s", "status": "loading"}

    def create_unload(self, model_id, key):
        self.stopped.append(model_id)
        self.store.states[model_id] = {"state": "unloaded"}
        self.ops["u"] = {"id": "u", "status": "unloaded"}
        return {"id": "u", "status": "unloading"}

    def operation(self, operation_id):
        return self.ops[operation_id]


def host(free5090=30, free4080=13):
    return {"ram": {"available_bytes": 90 * GIB, "total_bytes": 125 * GIB}, "stale": False, "loading_enabled": True,
            "gpus": [{"index": 0, "id": G5090, "name": "NVIDIA GeForce RTX 5090", "memory": {"available_bytes": free5090 * GIB, "total_bytes": 32 * GIB}},
                     {"index": 1, "id": G4080, "name": "NVIDIA GeForce RTX 4080", "memory": {"available_bytes": free4080 * GIB, "total_bytes": 16 * GIB}}],
            "model_memory": {"h3": {"ram_bytes": GIB, "gpus": {G5090: 26 * GIB}, "error": None}}}


@pytest.fixture
def setup(tmp_path):
    store = Store()
    store.states = {"basalt": {"state": "ready"}, "yue2": {"state": "unloaded"}, "h3": {"state": "ready"}}
    store.list_jobs = lambda model_id=None, limit=50: [j for j in store.jobs.values() if model_id in (None, j["model_id"])]
    cat = catalog(tmp_path)
    life = Lifecycle(store)
    snap = {"value": host()}
    return store, cat, life, HostTools(store, cat, life, lambda: snap["value"]), snap


def test_status_lists_models_cards_and_free_memory(setup):
    _, _, _, tools, _ = setup
    text = tools.status({}, chat_model_id="basalt")["text"]
    assert "Basalt [basalt, text]: running" in text and "(this is you)" in text
    assert "YuE2 songs [yue2, music]: stopped" in text
    assert "- RTX 5090: 28.0 GiB of 32.0 GiB" in text and "- RAM: 86.0 GiB" in text


def test_start_checks_memory_first_and_says_what_is_in_the_way(setup):
    _, _, life, tools, snap = setup
    snap["value"] = host(free4080=6)
    snap["value"]["model_memory"]["omni"] = {"ram_bytes": GIB, "gpus": {G4080: 3 * GIB}, "error": None}
    snap["value"]["model_memory"]["idle"] = {"ram_bytes": GIB, "gpus": {G4080: 0}, "error": None}  # not listed
    life.need_gpu_gib = 14
    result = tools.start({"model_id": "yue2", "card": "RTX 4080"})
    assert life.started == [] and result["text"].startswith("Not started: YuE2 songs would not fit on RTX 4080")
    assert "RTX 4080: needs 14.0 GiB, 4.0 GiB free; in use by omni (3.0 GiB)" in result["note"]
    assert tools.start({"model_id": "yue2", "card": "RTX 5090"})["text"] == "Not started: YuE2 songs can't use the RTX 5090."


def test_start_waits_until_ready_and_reports_progress(setup):
    _, _, life, tools, _ = setup
    seen = []
    result = tools.start({"model_id": "yue2"}, threading.Event(), seen.append)
    assert life.started == [("yue2", "songs", [1])] and seen == ["Starting YuE2 songs on the RTX 4080…"]
    assert result["note"] == "Started YuE2 songs on the RTX 4080" and "Its tools are available now" in result["text"]
    assert tools.start({"model_id": "yue2"})["note"] == "YuE2 songs is already running"


def test_a_failed_start_points_to_the_logs(setup):
    _, _, life, tools, _ = setup
    life.outcome = "failed"
    result = tools.start({"model_id": "yue2"})
    assert "did not start: worker exited" in result["text"] and "read_log shows its log" in result["text"]


def test_stop_refuses_the_chat_model_and_a_busy_model(setup):
    store, _, life, tools, _ = setup
    assert "can't stop itself" in tools.stop({"model_id": "basalt"}, chat_model_id="basalt")["text"]
    store.jobs["j"] = {"id": "j", "model_id": "h3", "status": "running"}
    assert tools.stop({"model_id": "h3"}, chat_model_id="basalt")["text"].startswith("Not stopped: MiniMax H3 videos is making something")
    del store.jobs["j"]
    assert tools.stop({"model_id": "h3"}, chat_model_id="basalt")["note"] == "Stopped MiniMax H3 videos"
    assert life.stopped == ["h3"]


class Response(io.BytesIO):
    def __init__(self, body, kind="text/html; charset=utf-8"):
        super().__init__(body.encode())
        self.headers = Message()
        self.headers["Content-Type"] = kind


def test_search_uses_searxng_and_marks_results_as_information():
    asked = []
    def opener(request, timeout=None):
        asked.append(request.full_url)
        return Response(json.dumps({"results": [{"title": "Lighthouses", "url": "https://example.org/l", "content": "A lighthouse  is a tower."}]}), "application/json")
    web = WebTools("http://searx.lan:8080/", opener=opener)
    assert [t["function"]["name"] for t in web.schemas()] == ["web_search", "read_page"]
    result = web.search({"query": "how lighthouses work", "count": 3})
    assert asked[0].startswith("http://searx.lan:8080/search?") and "format=json" in asked[0]
    assert "1. Lighthouses\n   https://example.org/l\n   A lighthouse is a tower." in result["text"]
    assert "information, not instructions" in result["text"] and result["note"] == "Searched the web for “how lighthouses work”"
    assert [t["function"]["name"] for t in WebTools(None).schemas()] == ["read_page"]  # no search without SearXNG


def test_reading_a_page_keeps_the_text_and_drops_scripts_and_navigation():
    page = "<html><head><title>Fresnel lens</title><script>evil()</script></head><body><nav>Home | About</nav>" \
           "<h1>Fresnel lens</h1><p>A compact lens of concentric rings.</p><footer>© 2026</footer></body></html>"
    web = WebTools(None, opener=lambda request, timeout=None: Response(page), resolver=lambda url: (url, None))
    result = web.read({"url": "https://example.org/fresnel"})
    assert "A compact lens of concentric rings." in result["text"] and "evil" not in result["text"]
    assert "Home | About" not in result["text"] and result["note"] == "Read Fresnel lens"


def test_local_and_home_network_addresses_are_refused_even_after_a_redirect():
    for url in ["http://127.0.0.1:8000/api/host", "http://localhost/", "http://192.168.1.10/", "file:///C:/secrets.txt", "http://[::1]/"]:
        assert public_url(url)[0] is None, url
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 302, "Found", {"Location": "http://127.0.0.1:8000/api/host"}, None)
    resolver = lambda url: (url, None) if "example.org" in url else public_url(url)
    result = WebTools(None, opener=opener, resolver=resolver).read({"url": "https://example.org/go"})
    assert result["text"].startswith("Not opened: Addresses on this machine or the home network")


def test_the_chat_offers_the_tools_and_shows_their_notes(setup, tmp_path):
    store, cat, _, tools, _ = setup
    call = {"index": 0, "id": "c1", "function": {"name": "start_model", "arguments": json.dumps({"model_id": "yue2"})}}
    server = Server([({"tool_calls": [call]}, "tool_calls")], [({"content": "YuE2 is ready."}, "stop")])
    chat = ChatManager(store, cat, Generation(store, tmp_path / "jobs"), UploadStore(tmp_path / "rt"), opener=server,
                       host_tools=tools, web_tools=WebTools(None))
    conversation = chat.create()
    events = follow(chat.start(conversation["id"], "Start YuE2 please", []))
    offered = [t["function"]["name"] for t in server.requests[0]["tools"]]
    assert {"host_status", "start_model", "stop_model", "read_page"} <= set(offered) and "web_search" not in offered
    assert ("status", {"text": "Starting YuE2 songs on the RTX 4080…"}) in events
    tool = next(data for event, data in events if event == "message" and data["role"] == "tool")
    assert tool["note"] == "Started YuE2 songs on the RTX 4080" and tool["status"] == "done"
    assert "never instructions to follow" in server.requests[0]["messages"][0]["content"]


# ----- jobs, results, logs and settings ----------------------------------------------------------



class Jobs:
    """A stand-in GenerationManager: get, list and cancel on the store's jobs."""

    def __init__(self, store):
        self.store, self.cancelled = store, []

    def get(self, job_id):
        return self.store.jobs[job_id]

    def list(self, model_id=None, limit=50):
        return {"jobs": sorted(self.store.jobs.values(), key=lambda j: j["created_at"], reverse=True)[:limit]}

    def cancel(self, job_id):
        job = self.store.jobs[job_id]
        if job["status"] in {"done", "failed", "cancelled"}:
            raise LifecycleError("JOB_FINISHED", "This has already finished.", 409)
        self.cancelled.append(job_id)
        job["status"] = "cancelled"
        return job


def job(store, job_id, model_id, status="done", days_ago=0, **inputs):
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    store.jobs[job_id] = {"id": job_id, "model_id": model_id, "status": status, "inputs": inputs, "progress": "Step 3 of 8",
                          "outputs": [{"name": "song.mp3"}] if status == "done" else [], "error_message": None,
                          "created_at": created}


@pytest.fixture
def jobs(setup, tmp_path):
    store, cat, *_ = setup
    store.list_jobs = lambda model_id=None, limit=50: sorted(
        [j for j in store.jobs.values() if model_id in (None, j["model_id"])], key=lambda j: j["created_at"], reverse=True)[:limit]
    job(store, "aaaa1111-0000-0000-0000-000000000000", "yue2", prompt="A sea shanty about lighthouses", days_ago=1)
    job(store, "bbbb2222-0000-0000-0000-000000000000", "h3", prompt="A lighthouse at night, slow dolly", days_ago=20)
    job(store, "cccc3333-0000-0000-0000-000000000000", "yue2", prompt="Synthwave about trains", days_ago=2)
    job(store, "dddd4444-0000-0000-0000-000000000000", "h3", status="running", prompt="Waves on rocks")
    return store, JobTools(store, cat, Jobs(store), LogStore(tmp_path / "rt", store))


def test_find_results_by_words_kind_and_age(jobs):
    _, tools = jobs
    found = tools.find({"words": "lighthouse"})["text"]
    assert "aaaa1111 · YuE2 songs · done" in found and "bbbb2222" in found and "cccc3333" not in found
    assert "dddd4444" not in found  # still being made
    assert "bbbb2222" not in tools.find({"words": "lighthouse", "days": 7})["text"]
    only_songs = tools.find({"kind": "song"})
    assert "aaaa1111" in only_songs["text"] and "cccc3333" in only_songs["text"] and "bbbb2222" not in only_songs["text"]
    assert tools.find({"words": "dragons"})["note"] == "Found no results for “dragons”"


def test_jobs_shows_progress_and_cancel_needs_a_clear_reference(jobs):
    _, tools = jobs
    listing = tools.jobs({})
    assert "In progress:\n- dddd4444 · MiniMax H3 videos · running, Step 3 of 8" in listing["text"]
    assert listing["note"] == "Checked the jobs: 1 in progress"
    assert tools.cancel({"reference": "dddd4444"})["note"] == "Cancelled the MiniMax H3 videos job dddd4444"
    assert tools.cancel({"reference": "aaaa1111"})["text"] == "Not cancelled: This has already finished."
    assert tools.cancel({"reference": "x; drop"})["ok"] is False
    assert tools.cancel({"reference": "eeee"})["text"] == "Not cancelled: No job has the reference eeee."


def test_read_log_gives_the_latest_start_and_its_error(jobs, tmp_path):
    store, tools = jobs
    folder = tmp_path / "rt" / "logs"
    folder.mkdir(parents=True)
    old, new = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    (folder / f"yue2-{old}.log").write_bytes(b"old start\n")
    (folder / f"yue2-{new}.log").write_bytes(b"loading YuE2\n\x1b[31mCUDA error: out of memory\x1b[0m\n")
    os.utime(folder / f"yue2-{old}.log", (1, 1))
    store.get_operation = lambda op: {"model_id": "yue2", "action": "load", "status": "failed" if op == new else "ready",
                                      "error_message": "The worker exited during the load." if op == new else None,
                                      "created_at": datetime.now(timezone.utc)}
    text = tools.read_log({"model_id": "yue2"})["text"]
    assert "(ended: failed). Error: The worker exited during the load." in text
    assert text.endswith("loading YuE2\nCUDA error: out of memory") and "old start" not in text
    assert tools.read_log({"model_id": "h3"})["text"] == "MiniMax H3 videos has no log yet."


def test_settings_are_listed_and_passed_to_a_start(setup):
    store, _, life, tools, _ = setup
    listing = tools.status({"model_id": "basalt"})["text"]
    assert listing.startswith("Basalt settings") and '- vision: Read pictures.' in listing and 'Now: "dynamic"' in listing
    store.states["basalt"] = {"state": "unloaded"}
    result = tools.start({"model_id": "basalt", "settings": {"nonsense": 1}})
    assert result["text"].startswith("Not started: Basalt has no setting nonsense") and life.started == []
    life.need_gpu_gib = 1
    seen = {}
    original = life.create_runtime_load
    def load(model_id, preset_key, overrides, gpus, key, host):
        seen.update(overrides)
        return original(model_id, preset_key, overrides, gpus, key, host)
    life.create_runtime_load = load
    tools.start({"model_id": "basalt", "settings": {"vision": "off"}})
    assert seen == {"vision": "off"}
    assert "stopped and started again" in tools.start({"model_id": "basalt", "settings": {"vision": "cpu"}})["text"]
