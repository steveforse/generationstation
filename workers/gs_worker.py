"""Generation Station worker protocol: a tiny HTTP server around one model.

Runs inside the model's own Python environment, so it uses the standard library only and never
imports Generation Station. A model worker supplies two functions:

    load(config) -> model            called once at start, in a background thread
    generate(model, inputs, job)     called for each job; writes files with job.output(...)

Protocol (127.0.0.1 only):

    GET  /health          {"status": "loading" | "loaded" | "failed", "error": str | null}
    POST /generate        {"job_id": str, "inputs": {...}}  -> 202 {"job_id", "status": "queued"}
    POST /jobs/{job_id}/provide {"name": str, "value": ...}  -> 200 the job; answers a request the job made with
                          job.need(name, request): while it waits, its details carry "needs": {name: request}
    POST /jobs/{job_id}/cancel  -> 200 the job; a queued job is cancelled at once, a running one
                          stops at its next progress report (job.report), then shows "cancelled"; its partial
                          results are removed, the files it was given are kept
    GET  /jobs/{job_id}   {"job_id", "status": "queued" | "running" | "done" | "failed" | "cancelled",
                           "progress": str | null, "outputs": [{"name", "mime", "bytes"}], "error",
                           "details": {...}}

Jobs run one at a time in arrival order. Outputs go to <output_dir>/<job_id>/. `details` holds what
the worker actually used (seed, steps, size, the full prompt sent to the model) plus `seconds`, the
time the job took; a finished job's inputs and details are also saved as <job_id>/job.json.
"""
import argparse
import json
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

JOB_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
THUMBNAIL = "thumbnail.jpg"  # a small preview the results list shows; not offered as a download
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _discard_outputs(job):
    """A cancelled job's partial results go; the files it was given (its inputs folder) stay with it."""
    for output in job.outputs:
        output["path"].unlink(missing_ok=True)
    job.outputs = []
    if job.dir.is_dir() and not any(job.dir.iterdir()):
        job.dir.rmdir()


class JobCancelled(Exception):
    """Raised inside generate() at the next progress report after a cancel request."""


class Job:
    def __init__(self, job_id, inputs, output_dir):
        self.job_id = job_id
        self.inputs = inputs
        self.dir = Path(output_dir) / job_id
        self.status = "queued"
        self.progress = None
        self.error = None
        self.outputs = []
        self.details = {}
        self.cancel_requested = False
        self.created = time.time()
        self.provided = {}
        self.answered = threading.Condition()

    def report(self, text):
        """Short human-readable progress, for example 'Writing the melody'.

        Also the point where a cancelled job stops: call it often (each step) so cancel is prompt."""
        if self.cancel_requested:
            raise JobCancelled()
        self.progress = str(text)[:200]

    def need(self, name, request, timeout=1800):
        """Ask the host for something this job cannot get itself (for example a running text model) and wait for
        the answer. While waiting, details["needs"][name] holds the request; a cancel ends the wait. Returns the value
        the host provided."""
        with self.answered:
            self.provided.pop(name, None)
            self.details.setdefault("needs", {})[name] = request
        deadline = time.time() + timeout
        try:
            with self.answered:
                while name not in self.provided:
                    if self.cancel_requested:
                        raise JobCancelled()
                    if time.time() > deadline:
                        raise TimeoutError(f"no answer from the host for {name} within {timeout} s")
                    self.answered.wait(2)
                return self.provided.pop(name)
        finally:
            with self.answered:
                needs = self.details.get("needs") or {}
                needs.pop(name, None)
                if not needs:
                    self.details.pop("needs", None)

    def provide(self, name, value):
        with self.answered:
            if name not in (self.details.get("needs") or {}):
                return False
            self.provided[name] = value
            self.answered.notify_all()
            return True

    def detail(self, **values):
        """Record what was actually used (seed, steps, size, full prompt), shown with the result."""
        self.details.update(values)

    def thumbnail(self, image, size=480):
        """Save a small JPEG preview of a PIL image (a picture, or a frame of a video)."""
        preview = image.convert("RGB")
        preview.thumbnail((size, size))
        preview.save(self.output(THUMBNAIL, "image/jpeg"), quality=82)
        self.details["thumbnail"] = THUMBNAIL

    def output(self, name, mime):
        """Return the path to write an output file to, and record it."""
        if not NAME.match(name):
            raise ValueError(f"Invalid output name {name!r}")
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / name
        self.outputs.append({"name": name, "mime": mime, "path": path})
        return path

    def as_dict(self):
        outputs = [{"name": o["name"], "mime": o["mime"],
                    "bytes": o["path"].stat().st_size if o["path"].exists() else 0} for o in self.outputs]
        return {"job_id": self.job_id, "status": self.status, "progress": self.progress,
                "outputs": outputs if self.status == "done" else [], "error": self.error,
                "details": self.details}


def serve(load, generate, argv=None, cleanup=None):
    """Run the worker. `cleanup(model)`, if given, runs after every job, finished, failed or cancelled,
    once the job's own references are gone (for example to hand cached GPU memory back)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    port = int(config["port"])
    output_dir = Path(config["output_dir"])
    state = {"status": "loading", "error": None, "model": None}
    jobs: dict[str, Job] = {}
    pending: queue.Queue[Job] = queue.Queue()
    lock = threading.Lock()

    def log(message):
        print(f"[worker] {message}", flush=True)

    def load_model():
        try:
            log("loading model")
            state["model"] = load(config)
            state["status"] = "loaded"
            log("model loaded")
        except Exception as exc:  # noqa: BLE001 - report it and keep serving /health so the failure is visible
            state["status"], state["error"] = "failed", f"{type(exc).__name__}: {exc}"
            log("load failed:\n" + traceback.format_exc())

    def run_jobs():
        while True:
            job = pending.get()
            if job.status == "cancelled":
                continue
            job.status = "running"
            log(f"job {job.job_id} started")
            started = time.perf_counter()
            try:
                generate(state["model"], job.inputs, job)
                missing = [o["name"] for o in job.outputs if not o["path"].exists()]
                if missing:
                    raise RuntimeError(f"Worker did not write {', '.join(missing)}")
                job.details["seconds"] = round(time.perf_counter() - started, 1)
                if job.dir.is_dir():
                    record = {"job_id": job.job_id, "inputs": job.inputs, "details": job.details,
                              "outputs": [{"name": o["name"], "mime": o["mime"]} for o in job.outputs]}
                    (job.dir / "job.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
                job.status = "done"
                log(f"job {job.job_id} done")
            except JobCancelled:
                job.status, job.progress = "cancelled", "Cancelled"
                _discard_outputs(job)
                log(f"job {job.job_id} cancelled while running")
            except Exception as exc:  # noqa: BLE001 - any model error fails only this job
                if job.cancel_requested:  # stopped by the cancel, wherever it surfaced
                    job.status, job.progress = "cancelled", "Cancelled"
                    _discard_outputs(job)
                    log(f"job {job.job_id} cancelled while running")
                    continue
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
                log(f"job {job.job_id} failed:\n" + traceback.format_exc())
            finally:
                if cleanup is not None and state["model"] is not None:
                    try:
                        cleanup(state["model"])
                    except Exception:  # noqa: BLE001 - clean-up must never stop the queue
                        log("clean-up after the job failed:\n" + traceback.format_exc())

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"status": state["status"], "error": state["error"]})
                return
            match = re.fullmatch(r"/jobs/([A-Za-z0-9-]{8,64})", self.path)
            job = jobs.get(match.group(1)) if match else None
            if job is None:
                self.send_json(404, {"error": "job not found"})
                return
            self.send_json(200, job.as_dict())

        def do_POST(self):
            provide = re.fullmatch(r"/jobs/([A-Za-z0-9-]{8,64})/provide", self.path)
            if provide:
                job = jobs.get(provide.group(1))
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length > 1_000_000:
                        raise ValueError("request too large")
                    payload = json.loads(self.rfile.read(length))
                    name = payload["name"]
                    if not isinstance(name, str):
                        raise TypeError("name is required")
                except (ValueError, KeyError, TypeError) as exc:
                    self.send_json(400, {"error": str(exc)})
                    return
                if job is None:
                    self.send_json(404, {"error": "job not found"})
                    return
                if not job.provide(name, payload.get("value")):
                    self.send_json(409, {"error": f"the job is not waiting for {name}"})
                    return
                log(f"job {job.job_id} was given {name}")
                self.send_json(200, job.as_dict())
                return
            cancel = re.fullmatch(r"/jobs/([A-Za-z0-9-]{8,64})/cancel", self.path)
            if cancel:
                with lock:
                    job = jobs.get(cancel.group(1))
                    if job is None:
                        self.send_json(404, {"error": "job not found"})
                        return
                    if job.status == "queued":
                        job.status, job.progress = "cancelled", "Cancelled"
                    elif job.status == "running":
                        job.cancel_requested = True
                        job.progress = "Cancelling"
                log(f"job {job.job_id} cancel requested ({job.status})")
                self.send_json(200, job.as_dict())
                return
            if self.path != "/generate":
                self.send_json(404, {"error": "not found"})
                return
            if state["status"] != "loaded":
                self.send_json(409, {"error": f"model is {state['status']}"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_000_000:
                    raise ValueError("request too large")
                payload = json.loads(self.rfile.read(length))
                job_id, inputs = payload["job_id"], payload["inputs"]
                if not isinstance(job_id, str) or not JOB_ID.match(job_id) or not isinstance(inputs, dict):
                    raise ValueError("job_id and inputs are required")
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
            with lock:
                if job_id in jobs:
                    self.send_json(202, jobs[job_id].as_dict())
                    return
                job = Job(job_id, inputs, output_dir)
                jobs[job_id] = job
            pending.put(job)
            self.send_json(202, job.as_dict())

        def log_message(self, *args):
            pass

    threading.Thread(target=load_model, name="load", daemon=True).start()
    threading.Thread(target=run_jobs, name="jobs", daemon=True).start()
    log(f"listening on 127.0.0.1:{port}")
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
