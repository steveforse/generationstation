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
from generationstation.chat_tools import JobTools
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

    def create_conversation(self, *, conversation_id, title, model_id, kind="chat"):
        now = datetime.now(timezone.utc)
        row = self.conversations[conversation_id] = {"id": conversation_id, "title": title, "model_id": model_id,
                                                     "created_at": now, "updated_at": now, "kind": kind}
        return row

    def latest_conversation(self, kind):
        rows = [(row["created_at"], n, row) for n, row in enumerate(self.conversations.values()) if row.get("kind") == kind]
        return max(rows, key=lambda item: item[:2])[2] if rows else None  # the newest inserted wins a timestamp tie

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
                    tool_call_id=None, job_id=None, status="done", error_message=None, note=None):
        row = {"id": str(uuid.uuid4()), "conversation_id": conversation_id, "role": role, "content": content, "note": note,
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


def test_a_turn_that_spends_every_round_on_tools_still_ends_with_an_answer(setup):
    """Seen 2026-11-24: eight page reads in a row left the chat on a tool result and 'thinking' for ever."""
    store, cat, generation, uploads = setup
    call = {"index": 0, "id": "c", "function": {"name": "read_page", "arguments": json.dumps({"url": "https://x.test/"})}}
    server = Server(*[[({"tool_calls": [call]}, "tool_calls")] for _ in range(8)],
                    [({"content": "I could not find a good answer."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create()
    events = follow(chat.start(conversation["id"], "Find me a BBQ spot", []), timeout=20)
    assert len(server.requests) == 9
    assert "tools" not in server.requests[8]  # the last request offers none, so it can only answer
    assert server.requests[8]["messages"][-1]["role"] == "user" and "all the tool calls" in server.requests[8]["messages"][-1]["content"]
    last = [m for m in store.messages if m["role"] != "tool"][-1]
    assert last["role"] == "assistant" and last["content"] == "I could not find a good answer." and last["status"] == "done"
    assert not any(m["content"].startswith("You have used all") for m in store.messages)  # the nudge is never saved
    assert [e for e, _ in events][-1] == "done"


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


def test_the_model_sees_what_its_jobs_made_and_results_it_shows(setup, tmp_path):
    """A made picture reaches the model with the next message; shown results right after the tool, as cards."""
    store, cat, generation, uploads = setup
    made = {"id": "5e5e5e5e-0000-0000-0000-000000000000", "model_id": "h3", "status": "done",
            "inputs": {"prompt": "a fox"}, "outputs": [{"name": "fox.png", "mime": "image/png"}]}
    older = {"id": "7f7f7f7f-0000-0000-0000-000000000000", "model_id": "h3", "status": "done",
             "inputs": {"prompt": "a lighthouse"}, "outputs": [{"name": "light.png", "mime": "image/png"}]}
    for job in (made, older):
        store.jobs[job["id"]] = job
        (tmp_path / "jobs" / job["id"]).mkdir(parents=True)
        (tmp_path / "jobs" / job["id"] / job["outputs"][0]["name"]).write_bytes(PNG)
    jobs = JobTools(store, cat, generation, None)
    chat = ChatManager(store, cat, generation, uploads, opener=Server(), job_tools=jobs)
    conversation = chat.create()
    cid = conversation["id"]
    store.add_message(cid, role="user", content="Make a fox")
    store.add_message(cid, role="assistant", tool_calls=[{"id": "c1", "name": "make_h3__text", "arguments": "{}"}])
    store.add_message(cid, role="tool", content="Started job 5e5e5e5e.", tool_call_id="c1", job_id=made["id"])
    store.add_message(cid, role="assistant", content="Started it.")
    store.add_message(cid, role="user", content="How does it look? And show me the lighthouse.")
    shown = jobs.show({"references": ["7f7f7f7f", "abcd9999"]})
    assert shown["attachments"] == [{"job_id": older["id"], "name": "light.png"}] and "No job has the reference abcd9999." in shown["text"]
    store.add_message(cid, role="assistant", tool_calls=[{"id": "c2", "name": "show_results", "arguments": "{}"}])
    store.add_message(cid, role="tool", content=shown["text"], tool_call_id="c2", attachments=shown["attachments"], note=shown["note"])
    context = chat._context(store.get_conversation(cid), {})
    question = context[5]["content"]
    assert question[0]["text"].startswith("[Finished since your answer: [result 5e5e5e5e: picture from MiniMax H3 videos")
    assert question[1]["type"] == "image_url" and question[2]["text"].startswith("How does it look?")
    assert context[7]["role"] == "tool" and context[8]["role"] == "user"
    assert context[8]["content"][0]["text"].startswith("[The results shown above") and context[8]["content"][1]["type"] == "image_url"
    # On the next turn those pictures are words: re-reading them on every request made answers much slower.
    store.add_message(cid, role="assistant", content="A fox in snow, and the lighthouse.")
    later = store.add_message(cid, role="user", content="Thanks")
    context = chat._context(store.get_conversation(cid), {})
    assert not any(isinstance(m["content"], list) and any(p.get("type") == "image_url" for p in m["content"]) for m in context)
    store.messages.remove(later)
    store.messages.pop()
    store.launches["basalt"]["launch"]["settings"]["vision"] = "off"  # picture reading off: words only, no extra message
    context = chat._context(store.get_conversation(cid), {})
    assert len(context) == 8 and all(part["type"] == "text" for part in context[5]["content"])
    assert jobs.show({"references": ["5e5e"]})["ok"] is True


def test_a_large_picture_reaches_the_model_as_its_thumbnail(setup, tmp_path):
    """A 4 MP picture took the chat model minutes to read; it gets the 1024 px thumbnail instead."""
    from generationstation.chat import png_size
    store, cat, generation, uploads = setup
    big = PNG[:8] + (13).to_bytes(4, "big") + b"IHDR" + (2656).to_bytes(4, "big") + (1504).to_bytes(4, "big") + b"\0" * 9
    job = {"id": "9a9a9a9a-0000-0000-0000-000000000000", "model_id": "h3", "status": "done", "inputs": {"prompt": "x"},
           "outputs": [{"name": "picture.png", "mime": "image/png"}, {"name": "thumbnail.jpg", "mime": "image/jpeg"}]}
    folder = tmp_path / "jobs" / job["id"]
    folder.mkdir(parents=True)
    (folder / "picture.png").write_bytes(big)
    (folder / "thumbnail.jpg").write_bytes(b"\xff\xd8thumb")
    chat = ChatManager(store, cat, generation, uploads, opener=Server())
    assert png_size(folder / "picture.png") == (2656, 1504) and png_size(folder / "thumbnail.jpg") is None
    assert chat._image_part(job, "picture.png")["image_url"]["url"].startswith("data:image/jpeg;base64,")
    (folder / "picture.png").write_bytes(PNG)  # a small picture goes as itself
    assert chat._image_part(job, "picture.png")["image_url"]["url"].startswith("data:image/png;base64,")


def test_the_help_assistant_keeps_one_thread_knows_the_app_and_the_page(setup):
    """The bubble opens the same conversation each time; it is taught the app and told which page is open."""
    store, cat, generation, uploads = setup
    server = Server([({"content": "Press **Make a song**."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    first = chat.assistant()
    assert first["conversation"]["kind"] == "assistant" and first["conversation"]["title"] == "Assistant"
    assert chat.assistant()["conversation"]["id"] == first["conversation"]["id"]
    events = follow(chat.start(first["conversation"]["id"], "How do I make a song?", [], where="YuE2 songs page"))
    assert ("done", {}) in events or events[-1][0] == "done"
    system = server.requests[0]["messages"][0]["content"]
    assert system.startswith("You are the help assistant of Generation Station")
    assert "- **YuE2 songs** (menu: Music; now running; id yue2)" in system
    assert "The person is looking at: YuE2 songs page." in system and "# Your tools" in system
    assert chat.get(first["conversation"]["id"])["conversation"]["title"] == "Assistant"  # not renamed by the question
    fresh = chat.assistant(fresh=True)
    assert fresh["conversation"]["id"] != first["conversation"]["id"] and fresh["messages"] == []
    assert chat.assistant()["conversation"]["id"] == fresh["conversation"]["id"]
    # A Chat page conversation is not taught the guide.
    plain = chat.create()
    assert plain["kind"] == "chat"
    assert not chat._context(store.get_conversation(plain["id"]), {})[0]["content"].startswith("You are the help assistant")


def test_the_assistant_uses_a_running_model_and_prefers_the_one_marked_for_it(setup, tmp_path):
    """A running chat model answers, the marked one (`assistant`, Inkling on the desktop) if it is among them; with
    none running, the marked one is the one to start."""
    store, _, generation, uploads = setup
    entry = {"kind": "basalt", "workload": "text", "executable": "basalt.exe", "default_preset": "fn", "presets": {"fn": {
        "name": "FN", "alias": "FN", "model_path": "D:/fn.basalt", "gpus": [0], "settings": {},
        "estimate": {"ram_gib": 4, "gpu_min_free_gib": {"0": 4}}}}}
    cat = parse_catalog({"runtimes": {"big": {**entry, "name": "Big model", "port": 8160},
                                      "helper": {**entry, "name": "Helper", "port": 8161, "assistant": True}}})
    chat = ChatManager(store, cat, generation, uploads, opener=Server())
    store.states = {"big": {"state": "unloaded"}, "helper": {"state": "unloaded"}}
    assert chat.assistant_model() == "helper"  # nothing running: the one to start
    store.states = {"big": {"state": "ready"}, "helper": {"state": "unloaded"}}
    assert chat.assistant()["conversation"]["model_id"] == "big"  # a running model answers, whatever it is
    assert chat.create()["model_id"] == "big"
    store.states = {"big": {"state": "ready"}, "helper": {"state": "ready"}}
    assert chat.assistant()["conversation"]["model_id"] == "helper"  # both running: the marked one
    row = store.latest_conversation("assistant")
    store.update_conversation(row["id"], model_id="big")
    assert chat.assistant()["conversation"]["model_id"] == "helper"


def test_only_the_assistant_calls_itself_the_assistant(setup, tmp_path):
    store, _, generation, uploads = setup
    entry = {"kind": "basalt", "workload": "text", "executable": "basalt.exe", "default_preset": "fn", "presets": {"fn": {
        "name": "FN", "alias": "FN", "model_path": "D:/fn.basalt", "gpus": [0], "settings": {},
        "estimate": {"ram_gib": 4, "gpu_min_free_gib": {"0": 4}}}}}
    cat = parse_catalog({"runtimes": {"big": {**entry, "name": "Big model", "port": 8160}}})
    store.states = {"big": {"state": "ready"}}
    chat = ChatManager(store, cat, generation, uploads, opener=Server())
    general = chat._conversation(chat.create()["id"])
    helper = chat._conversation(chat.assistant()["conversation"]["id"])
    system = lambda conversation: chat._context(conversation, {})[0]["content"]
    assert "You are the assistant" not in system(general) and "chat model running on the user's own computer" in system(general)
    assert system(helper).count("You are the assistant inside Generation Station") == 1


def test_a_message_can_move_the_conversation_to_another_running_chat_model(setup, tmp_path):
    store, _, generation, uploads = setup
    entry = {"kind": "basalt", "workload": "text", "executable": "basalt.exe", "default_preset": "fn", "presets": {"fn": {
        "name": "FN", "alias": "FN", "model_path": "D:/fn.basalt", "gpus": [0], "settings": {},
        "estimate": {"ram_gib": 4, "gpu_min_free_gib": {"0": 4}}}}}
    cat = parse_catalog({"runtimes": {"big": {**entry, "name": "Big model", "port": 8160},
                                      "helper": {**entry, "name": "Helper", "port": 8161},
                                      "off": {**entry, "name": "Stopped", "port": 8162}}})
    store.states = {"big": {"state": "ready"}, "helper": {"state": "ready"}, "off": {"state": "unloaded"}}
    server = Server(*[[({"content": "ok"}, "stop")] for _ in range(3)])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create("big")
    assert conversation["model_id"] == "big"
    # A model that is not running, or is not a chat model, is refused and the conversation stays where it was.
    for target, code in [("off", "MODEL_NOT_READY"), ("nowhere", "MODEL_NOT_FOUND")]:
        with pytest.raises(LifecycleError) as refused:
            chat.start(conversation["id"], "hi", [], model_id=target)
        assert refused.value.code == code
    assert chat.get(conversation["id"])["conversation"]["model_id"] == "big" and chat.get(conversation["id"])["messages"] == []
    follow(chat.start(conversation["id"], "hi", [], model_id="helper"))
    assert chat.get(conversation["id"])["conversation"]["model_id"] == "helper"
    # Naming the model it is already on changes nothing, and the help assistant keeps its own model.
    follow(chat.start(conversation["id"], "again", [], model_id="helper"))
    assistant = chat.assistant()["conversation"]
    chat.start(assistant["id"], "hello", [], model_id="big")
    assert chat.get(assistant["id"])["conversation"]["model_id"] == assistant["model_id"]


def leveled_chat(tmp_path, levels=("minimal", "low", "high", "max"), default="low", off=True):
    """A chat with a text model whose card declares its thinking levels."""
    card = {"engine": "basalt", "executable": "basalt.exe", "alias": "Ink", "model_path": "D:/ink.basalt",
            "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"0": 24}}, "thinking_levels": list(levels),
            "thinking_default": default, "thinking_off": off}
    cat = parse_catalog({"runtimes": {"ink": {
        "kind": "llm", "name": "Inkling", "workload": "text", "port": 8161, "default_preset": "main",
        "presets": {"main": {"name": "Inkling", "gpus": [0], "settings": {}, "cards": {"0": card},
                             "estimate": {"ram_gib": 6, "gpu_min_free_gib": {"0": 24}}}}}}})
    store = Store()
    store.states["ink"] = {"state": "ready"}
    store.launches["ink"] = {"launch": {"preset": "main", "settings": {}, "gpus": [0]}}
    server = Server([({"content": "Hi."}, "stop")] * 6)
    chat = ChatManager(store, cat, Generation(store, tmp_path / "jobs"), UploadStore(tmp_path / "runtime"), opener=server)
    return chat, server


def test_a_chosen_thinking_level_is_sent_and_one_the_model_lacks_is_refused(tmp_path):
    chat, server = leveled_chat(tmp_path)
    conversation = chat.create("ink")["id"]
    assert chat.thinking_for("ink") == {"levels": ["minimal", "low", "high", "max"], "default": "low", "off": True}
    follow(chat.start(conversation, "hi", [], thinking="high"))
    assert server.requests[-1]["reasoning_effort"] == "high" and "enable_thinking" not in server.requests[-1]
    follow(chat.start(conversation, "hi", [], thinking=True))  # on: the model's default level
    assert server.requests[-1]["reasoning_effort"] == "low"
    follow(chat.start(conversation, "hi", [], thinking="off"))
    assert server.requests[-1]["enable_thinking"] is False and server.requests[-1]["reasoning_effort"] == "none"
    with pytest.raises(LifecycleError) as refused:
        chat.start(conversation, "hi", [], thinking="xhigh")
    assert refused.value.code == "THINKING_LEVEL_INVALID" and "off, minimal, low, high, max" in refused.value.message


def test_a_model_that_cannot_turn_thinking_off_gets_its_lowest_level(tmp_path):
    chat, server = leveled_chat(tmp_path, levels=("low", "high"), default="high", off=False)
    follow(chat.start(chat.create("ink")["id"], "hi", [], thinking=False))
    assert server.requests[-1]["reasoning_effort"] == "low" and "enable_thinking" not in server.requests[-1]


def test_the_message_request_takes_on_off_or_a_level_name():
    from pydantic import ValidationError

    from generationstation.app import ChatMessageRequest
    for value in (True, False, "off", "high"):
        assert ChatMessageRequest(text="hi", thinking=value).thinking == value
    assert ChatMessageRequest(text="hi").thinking is True
    for bad in ("x" * 21, 3, None):
        with pytest.raises(ValidationError):
            ChatMessageRequest(text="hi", thinking=bad)
