"""Text models for worker jobs that ask for one (plugins with `text_model_jobs`, such as meeting notes).

A worker job calls job.need("text_model", {"model": "auto" | <model id>, "gpu": <its card>}) and waits. The broker
notices the request (it polls those jobs in the background, so nobody has to watch the page), picks the model, starts
it through the host's own start path (capacity checks, admission, the same waiting as the chat's start_model tool)
unless it is already running, and answers with its address. A model the broker started is stopped again when no job
that asked for it is still running, so a one-card flow (speech, then text) leaves the card as it found it.
"""
import threading
import time

from .chat_tools import short

TERMINAL = {"done", "failed", "cancelled"}


class TextModelBroker:
    def __init__(self, store, catalog, host_tools, chat=None, interval=3.0, log=print):
        self.store, self.catalog, self.host_tools, self.chat = store, catalog, host_tools, chat
        self.interval, self.log = interval, log
        self.handling: set[str] = set()          # job ids being answered now
        self.started: dict[str, set[str]] = {}   # model id -> job ids it was started for
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, name="text-model-broker", daemon=True).start()

    def close(self):
        self.stopped.set()

    def _loop(self):
        while not self.stopped.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must keep running
                self.log(f"[text models] {type(exc).__name__}: {exc}")

    # ----- one pass ---------------------------------------------------------------------------------

    def tick(self):
        states = self.store.runtime_states()
        live = set()
        for model_id, runtime in self.catalog.runtimes.items():
            plugin = self.catalog.plugin(model_id)
            if not getattr(plugin, "text_model_jobs", False) or (states.get(model_id) or {}).get("state") != "ready":
                continue
            for job in self.store.list_jobs(model_id, 50):
                if job["status"] in TERMINAL:
                    continue
                record = plugin.job_status(runtime, job["id"]) or {}
                if record.get("status") in TERMINAL:
                    continue
                live.add(job["id"])
                request = ((record.get("details") or {}).get("needs") or {}).get("text_model")
                if request is None:
                    continue
                with self.lock:
                    if job["id"] in self.handling:
                        continue
                    self.handling.add(job["id"])
                threading.Thread(target=self._answer, args=(model_id, runtime, plugin, job["id"], request),
                                 name=f"text-model-{job['id'][:8]}", daemon=True).start()
        self._release(live)

    def _release(self, live):
        """Stop each model the broker started once no job it was started for is still running."""
        with self.lock:
            done = [m for m, jobs in self.started.items() if not (jobs & live) and not (jobs & self.handling)]
        for model_id in done:
            if self._chatting(model_id):
                continue  # someone is chatting with it now; leave it running
            result = self.host_tools.stop({"model_id": model_id})
            self.log(f"[text models] {result.get('note')}")
            with self.lock:
                self.started.pop(model_id, None)

    def _chatting(self, model_id):
        """Whether a chat is answering on this model right now."""
        if self.chat is None:
            return False
        for conversation_id in list(getattr(self.chat, "turns", {})):
            try:
                if self.chat._conversation(conversation_id).get("model_id") == model_id:
                    return True
            except Exception:  # noqa: BLE001, S112 - a conversation deleted meanwhile
                continue
        return False

    # ----- answering a job ----------------------------------------------------------------------------

    def _answer(self, owner_id, owner, plugin, job_id, request):
        try:
            value = self._provide(owner, job_id, request if isinstance(request, dict) else {})
        except Exception as exc:  # noqa: BLE001 - the job gets the reason instead of waiting forever
            value = {"error": f"{type(exc).__name__}: {exc}"}
        try:
            status, body = _post(owner.port, job_id, value)
            if status != 200:
                self.log(f"[text models] job {job_id[:8]} did not take the answer ({status}: {body})")
        finally:
            with self.lock:
                self.handling.discard(job_id)

    def _provide(self, owner, job_id, request):
        states = self.store.runtime_states()
        chat_models = [m for m, r in self.catalog.runtimes.items() if self.catalog.plugin(m).chats]
        wanted = request.get("model") or "auto"
        if wanted == "auto":
            running = [m for m in chat_models if (states.get(m) or {}).get("state") == "ready"]
            wanted = running[0] if running else getattr(owner, "default_text_model", None) or (chat_models or [None])[0]
        if wanted not in chat_models:
            return {"error": f"There is no text model {wanted!r}."}
        runtime = self.catalog.runtimes[wanted]
        if (states.get(wanted) or {}).get("state") != "ready":
            result = self._start(wanted, request.get("gpu"))
            if (self.store.runtime_states().get(wanted) or {}).get("state") != "ready":
                return {"error": result.get("text") or f"{runtime.name} did not start."}
            with self.lock:
                self.started.setdefault(wanted, set()).add(job_id)
        elif wanted in self.started:
            with self.lock:
                self.started[wanted].add(job_id)
        launch = (self.store.latest_launches().get(wanted) or {}).get("launch") or {}
        preset = runtime.presets.get(launch.get("preset")) or runtime.presets[runtime.default_preset]
        plugin = self.catalog.plugin(wanted)
        served = self.chat._served_model(runtime) if self.chat is not None else "default"
        chat_thinking = getattr(plugin, "chat_thinking", None)
        thinking = (chat_thinking(preset, launch.get("gpus") or preset.gpus) if chat_thinking else None) or {}
        # A model that always thinks (Inkling) cannot be told "no thinking"; its lowest level keeps the thinking brief.
        lowest = thinking["levels"][0] if thinking.get("levels") and not thinking.get("off") else None
        return {"thinking_floor": lowest, "base_url": f"http://127.0.0.1:{runtime.port}", "model": served, "model_id": wanted, "name": runtime.name,
                "sampling": plugin.chat_sampling(preset, launch.get("gpus") or preset.gpus),
                "can_correct": wanted not in (getattr(owner, "no_correction_models", None) or [])}

    def _start(self, model_id, gpu):
        """Start on the asking job's card when the model can run there alone (the one-card flow), else as usual."""
        if gpu is not None:
            cards = self.host_tools._cards(self.host_tools.snapshot())
            name = short((cards.get(gpu) or {}).get("name") or "")
            if name:
                result = self.host_tools.start({"model_id": model_id, "card": name})
                if not result.get("text", "").startswith("Not started"):
                    return result
                self.log(f"[text models] {result.get('note')}; trying its usual cards")
        return self.host_tools.start({"model_id": model_id})


def _post(port, job_id, value, attempts=3):
    from .plugins.worker import _request
    for attempt in range(attempts):
        status, body = _request("POST", f"http://127.0.0.1:{port}/jobs/{job_id}/provide",
                                {"name": "text_model", "value": value}, timeout=10)
        if status is not None:
            return status, body
        time.sleep(2)
    return None, None
