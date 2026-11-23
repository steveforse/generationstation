"""Chat: a turn streams the text model's answer, saves it, and runs tool calls as generation jobs.
No model runs: the server's stream is canned and the store is in memory."""
import io
import json
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest

from generationstation.chat import ChatManager, tool_name
from generationstation.lifecycle import LifecycleError
from generationstation.plugins import get_plugin
from generationstation.runtimes import parse_catalog
from generationstation.uploads import UploadStore

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def catalog(tmp_path):
    return parse_catalog({"runtimes": {
        "basalt": {
            "kind": "basalt", "name": "Basalt", "workload": "text", "executable": "basalt.exe", "port": 8160,
            "default_preset": "fn", "presets": {"fn": {
                "name": "Flash-Next", "alias": "FN", "model_path": "D:/fn.basalt", "gpus": [0],
                "settings": {"vision": "dynamic"}, "estimate": {"ram_gib": 40, "gpu_min_free_gib": {"0": 24}}}}},
        "yue2": {
            "kind": "yue2", "name": "YuE2 songs", "workload": "music", "port": 8170, "python": sys.executable,
            "output_dir": str(tmp_path / "out"), "default_preset": "songs", "presets": {"songs": {
                "name": "YuE2", "gpus": [1], "options": {"model_dir": "m", "vae_dir": "v"},
                "settings": {}, "estimate": {"ram_gib": 8, "gpu_min_free_gib": {"1": 14}}}}},
        "h3": {
            "kind": "minimax_h3", "name": "MiniMax H3 videos", "workload": "video", "port": 8190,
            "python": sys.executable, "output_dir": str(tmp_path / "h3"), "default_preset": "h3",
            "presets": {"h3": {"name": "H3", "gpus": [0], "options": {}, "settings": {},
                               "estimate": {"ram_gib": 8, "gpu_min_free_gib": {"0": 29}}}}},
    }})


class Store:
    def __init__(self):
        self.states = {"basalt": {"state": "ready"}, "yue2": {"state": "ready"}, "h3": {"state": "ready"}}
        self.launches = {"basalt": {"launch": {"preset": "fn", "settings": {"vision": "dynamic"}, "gpus": [0]}}}
        self.conversations, self.messages, self.jobs = {}, [], {}

    def runtime_states(self):
        return self.states

    def latest_launches(self):
        return self.launches

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def find_jobs_by_prefix(self, prefix, limit=2):
        return [job for job in self.jobs.values() if job["id"].startswith(prefix)][:limit]

    def list_conversations(self, limit=200):
        return sorted(self.conversations.values(), key=lambda row: row["updated_at"], reverse=True)

    def create_conversation(self, *, conversation_id, title, model_id):
        now = datetime.now(timezone.utc)
        row = self.conversations[conversation_id] = {"id": conversation_id, "title": title, "model_id": model_id,
                                                     "created_at": now, "updated_at": now}
        return row

    def get_conversation(self, conversation_id):
        return self.conversations.get(conversation_id)

    def update_conversation(self, conversation_id, **values):
        self.conversations[conversation_id].update(values, updated_at=datetime.now(timezone.utc))
        return self.conversations[conversation_id]

    def delete_conversation(self, conversation_id):
        self.messages = [m for m in self.messages if m["conversation_id"] != conversation_id]
        return self.conversations.pop(conversation_id, None) is not None

    def list_messages(self, conversation_id):
        return [m for m in self.messages if m["conversation_id"] == conversation_id]

    def add_message(self, conversation_id, *, role, content="", reasoning=None, attachments=None, tool_calls=None,
                    tool_call_id=None, job_id=None, status="done", error_message=None):
        row = {"id": str(uuid.uuid4()), "conversation_id": conversation_id, "role": role, "content": content,
               "reasoning": reasoning or None, "attachments": attachments or [], "tool_calls": tool_calls or [],
               "tool_call_id": tool_call_id, "job_id": job_id, "status": status, "error_message": error_message,
               "created_at": datetime.now(timezone.utc), "position": len(self.list_messages(conversation_id)) + 1}
        self.messages.append(row)
        return row


class Generation:
    def __init__(self, store, root):
        self.store, self.root, self.created = store, root, []

    def create(self, model_id, inputs):
        if model_id == "yue2" and not inputs.get("lyrics"):
            raise LifecycleError("INPUTS_INVALID", "Lyrics is required.", 422)
        job = {"id": str(uuid.uuid4()), "model_id": model_id, "inputs": inputs, "status": "queued", "outputs": []}
        self.created.append(job)
        self.store.jobs[job["id"]] = job
        return job

    def output_path(self, job_id, name):
        return self.root / job_id / name, "image/png"


class Server:
    """Stands in for Basalt: /v1/models, and one canned stream per chat request."""
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request, timeout=None):
        if isinstance(request, str):
            return io.BytesIO(json.dumps({"data": [{"id": "FN"}]}).encode())
        self.requests.append(json.loads(request.data))
        chunks = self.answers.pop(0)
        lines = [f"data: {json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]})}\n\n"
                 for delta, finish in chunks] + ["data: [DONE]\n\n"]
        return io.BytesIO("".join(lines).encode())


def follow(turn, timeout=10):
    events, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        event, data = turn.events.get(timeout=timeout)
        events.append((event, data))
        if event == "done":
            return events
    raise AssertionError("the turn did not finish")


@pytest.fixture
def setup(tmp_path):
    store = Store()
    cat = catalog(tmp_path)
    generation = Generation(store, tmp_path / "jobs")
    return store, cat, generation, UploadStore(tmp_path / "runtime")


def test_an_answer_streams_and_is_saved_with_its_thinking(setup):
    store, cat, generation, uploads = setup
    server = Server([({"reasoning_content": "Hmm."}, None), ({"content": "Hello"}, None), ({"content": " there."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create()
    assert conversation["model_id"] == "basalt" and conversation["title"] == "New conversation"
    events = follow(chat.start(conversation["id"], "  Say hello  ", []))
    deltas = [data for event, data in events if event == "delta"]
    assert deltas == [{"reasoning": "Hmm."}, {"content": "Hello"}, {"content": " there."}]
    saved = chat.get(conversation["id"])
    assert saved["conversation"]["title"] == "Say hello" and not saved["conversation"]["busy"]
    user, answer = saved["messages"]
    assert (user["role"], user["content"]) == ("user", "Say hello")
    assert (answer["content"], answer["reasoning"], answer["status"]) == ("Hello there.", "Hmm.", "done")
    request = server.requests[0]
    assert request["model"] == "FN" and request["stream"] is True
    assert request["messages"][0]["role"] == "system" and "Running now: MiniMax H3 videos, YuE2 songs" in request["messages"][0]["content"]
    assert request["messages"][-1] == {"role": "user", "content": "Say hello"}


def test_tools_offer_each_way_of_making_on_running_models(setup):
    store, cat, generation, uploads = setup
    store.states["h3"] = {"state": "unloaded"}
    tools, _ = ChatManager(store, cat, generation, uploads)._tools()
    names = [tool["function"]["name"] for tool in tools]
    assert names == [tool_name("yue2", mode) for mode in get_plugin("yue2").modes] or names == [tool_name("yue2")]
    song = tools[0]["function"]["parameters"]
    assert {"style", "lyrics"} <= set(song["required"]) and song["properties"]["lyrics"]["type"] == "string"
    store.states["h3"] = {"state": "ready"}
    tools, _ = ChatManager(store, cat, generation, uploads)._tools()
    pictures = next(t for t in tools if t["function"]["name"] == tool_name("h3", "frames"))["function"]["parameters"]
    assert pictures["properties"]["first"]["type"] == "array"


def test_a_tool_call_starts_a_job_and_the_model_then_replies(setup):
    store, cat, generation, uploads = setup
    name = tool_name("yue2", next(iter(get_plugin("yue2").modes), None))
    call = {"index": 0, "id": "call_1", "function": {"name": name, "arguments": ""}}
    args = {"index": 0, "function": {"arguments": json.dumps({"style": "dream pop", "lyrics": "[Verse]\nla"})}}
    server = Server([({"tool_calls": [call]}, None), ({"tool_calls": [args]}, "tool_calls")],
                    [({"content": "Started your song."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create()
    events = follow(chat.start(conversation["id"], "Make a dream pop song", []))
    assert [e for e, _ in events].count("message") == 4  # user, call, tool result, reply
    job = generation.created[0]
    assert job["model_id"] == "yue2" and job["inputs"]["style"] == "dream pop"
    tool = next(data for event, data in events if event == "message" and data["role"] == "tool")
    assert tool["job_id"] == job["id"] and tool["job"]["id"] == job["id"]
    second = server.requests[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == name
    assert second[-1]["role"] == "tool" and "still being made" in second[-1]["content"]
    # Later turns see the job as it is now.
    job.update(status="done", outputs=[{"name": "song.wav", "mime": "audio/wav"}])
    context = chat._context(store.get_conversation(conversation["id"]), {})
    assert context[3]["content"].startswith(f"Done. [result {job['id'][:8]}: sound recording from YuE2 songs")


def test_a_refused_tool_call_is_reported_to_the_model(setup):
    store, cat, generation, uploads = setup
    name = tool_name("yue2", next(iter(get_plugin("yue2").modes), None))
    call = {"index": 0, "id": "c", "function": {"name": name, "arguments": json.dumps({"style": "pop"})}}
    server = Server([({"tool_calls": [call]}, "tool_calls")], [({"content": "Sorry."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create()
    follow(chat.start(conversation["id"], "song", []))
    tool = next(m for m in store.messages if m["role"] == "tool")
    assert tool["status"] == "error" and tool["content"] == "Not started: Lyrics is required."
    assert not generation.created


def test_attached_pictures_reach_the_model_and_feed_tools_by_reference(setup, tmp_path):
    store, cat, generation, uploads = setup
    picture = {"id": "1a2b3c4d" + "-0000-0000-0000-000000000000", "model_id": "h3", "status": "done",
               "inputs": {"prompt": "a lighthouse"}, "outputs": [{"name": "picture.png", "mime": "image/png"}]}
    store.jobs[picture["id"]] = picture
    (tmp_path / "jobs" / picture["id"]).mkdir(parents=True)
    (tmp_path / "jobs" / picture["id"] / "picture.png").write_bytes(PNG)
    call = {"index": 0, "id": "c", "function": {"name": tool_name("h3", "frames"),
                                                "arguments": json.dumps({"prompt": "waves", "first": ["1a2b3c4d"]})}}
    server = Server([({"tool_calls": [call]}, "tool_calls")], [({"content": "Animating it."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create()
    follow(chat.start(conversation["id"], "Animate this", [{"job_id": picture["id"], "name": "picture.png"}]))
    parts = server.requests[0]["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "Animate this"}
    assert parts[1]["text"].startswith("[result 1a2b3c4d: picture from MiniMax H3 videos, file picture.png;")
    assert parts[2]["image_url"]["url"].startswith("data:image/png;base64,")
    job = generation.created[0]
    upload = uploads.get(job["inputs"]["first"][0])
    assert upload["kind"] == "image" and job["inputs"]["mode"] == "frames"
    # With picture reading off, only the words go.
    store.launches["basalt"]["launch"]["settings"]["vision"] = "off"
    context = chat._context(store.get_conversation(conversation["id"]), {})
    assert all(part["type"] == "text" for part in context[1]["content"])


def test_turn_rules(setup):
    store, cat, generation, uploads = setup
    chat = ChatManager(store, cat, generation, uploads, opener=Server())
    conversation = chat.create()
    for text, attachments, code in [("", [], "MESSAGE_EMPTY"), ("x" * 20_001, [], "MESSAGE_TOO_LONG"),
                                    ("hi", [{"job_id": "nope", "name": "a.png"}], "ATTACHMENT_NOT_FOUND")]:
        with pytest.raises(LifecycleError) as refused:
            chat.start(conversation["id"], text, attachments)
        assert refused.value.code == code
    store.states["basalt"] = {"state": "unloaded"}
    with pytest.raises(LifecycleError) as not_ready:
        chat.start(conversation["id"], "hi", [])
    assert not_ready.value.code == "MODEL_NOT_READY"
    assert chat.rename(conversation["id"], "  Trip   plans ")["title"] == "Trip plans"
    assert chat.delete(conversation["id"])["deleted"] and chat.list() == {"conversations": []}


def test_basalt_reads_pictures_only_when_asked_and_reserves_ram_for_it():
    plugin = get_plugin("basalt")
    runtime = parse_catalog({"runtimes": {"basalt": {
        "kind": "basalt", "name": "Basalt", "workload": "text", "executable": "basalt.exe", "port": 8160,
        "default_preset": "ds", "presets": {"ds": {
            "name": "DS", "alias": "DS", "model_path": "D:/ds.basalt", "gpus": [0], "vision_options": ["dynamic", "off"],
            "settings": {"vision": "dynamic"}, "estimate": {"ram_gib": 16, "gpu_min_free_gib": {"0": 24}}}}}}}).runtimes["basalt"]
    preset = runtime.presets["ds"]
    assert plugin.choice_options(preset, "vision") == ["dynamic", "off"]
    assert plugin.config(runtime, preset, {"vision": "dynamic"}, [0])["models"][0]["vision"] == "dynamic"
    assert plugin.estimate(runtime, preset, {"vision": "dynamic"}, [0])[0] == 17
    assert plugin.estimate(runtime, preset, {"vision": "off"}, [0])[0] == 16


def test_thinking_off_asks_for_no_thinking_both_ways(setup):
    store, cat, generation, uploads = setup
    server = Server([({"content": "Hi."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    follow(chat.start(chat.create()["id"], "hi", [], thinking=False))
    assert server.requests[0]["enable_thinking"] is False and server.requests[0]["reasoning_effort"] == "none"


def test_a_basalt_model_can_run_on_its_own_install(tmp_path):
    plugin = get_plugin("basalt")
    runtime = parse_catalog({"runtimes": {"basalt": {
        "kind": "basalt", "name": "Basalt", "workload": "text", "executable": "C:/basalt/bin/basalt.exe",
        "working_dir": "C:/basalt", "path_prepend": ["C:/cuda"], "port": 8160, "default_preset": "ds", "presets": {
            "ds": {"name": "DS", "alias": "DS", "model_path": "D:/ds.basalt", "gpus": [0],
                   "estimate": {"ram_gib": 16, "gpu_min_free_gib": {"0": 24}}},
            "ink": {"name": "Inkling", "alias": "Ink", "model_path": "D:/ink.basalt", "gpus": [0],
                    "executable": "C:/basalt-new/bin/basalt.exe", "working_dir": "C:/basalt-new",
                    "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"0": 24}}}}}}}).runtimes["basalt"]
    old = plugin.launch(runtime, runtime.presets["ds"], {}, [0], {"PATH": "P"}, tmp_path)
    new = plugin.launch(runtime, runtime.presets["ink"], {}, [0], {"PATH": "P"}, tmp_path)
    assert (old.argv[0], old.cwd) == ("C:/basalt/bin/basalt.exe", "C:/basalt")
    assert (new.argv[0], new.cwd) == ("C:/basalt-new/bin/basalt.exe", "C:/basalt-new")
    assert new.env["PATH"] == "C:/cuda;P"  # the runtime's CUDA path unless the preset names its own
