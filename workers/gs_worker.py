"""Generation Station worker protocol: a tiny HTTP server around one model.

Runs inside the model's own Python environment, so it uses the standard library only and never
imports Generation Station. A model worker supplies two functions:

    load(config) -> model            called once at start, in a background thread
    generate(model, inputs, job)     called for each job; writes files with job.output(...)

Protocol (127.0.0.1 only):

    GET  /health          {"status": "loading" | "loaded" | "failed", "error": str | null}
    POST /generate        {"job_id": str, "inputs": {...}}  -> 202 {"job_id", "status": "queued"}
    GET  /jobs/{job_id}   {"job_id", "status": "queued" | "running" | "done" | "failed",
                           "progress": str | null, "outputs": [{"name", "mime", "bytes"}], "error"}

Jobs run one at a time in arrival order. Outputs go to <output_dir>/<job_id>/.
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
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


class Job:
    def __init__(self, job_id, inputs, output_dir):
        self.job_id = job_id
        self.inputs = inputs
        self.dir = Path(output_dir) / job_id
        self.status = "queued"
        self.progress = None
        self.error = None
        self.outputs = []
        self.created = time.time()

    def report(self, text):
        """Short human-readable progress, for example 'Writing the melody'."""
        self.progress = str(text)[:200]

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
                "outputs": outputs if self.status == "done" else [], "error": self.error}


def serve(load, generate, argv=None):
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
            job.status = "running"
            log(f"job {job.job_id} started")
            try:
                generate(state["model"], job.inputs, job)
                missing = [o["name"] for o in job.outputs if not o["path"].exists()]
                if missing:
                    raise RuntimeError(f"Worker did not write {', '.join(missing)}")
                job.status = "done"
                log(f"job {job.job_id} done")
            except Exception as exc:  # noqa: BLE001 - any model error fails only this job
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
                log(f"job {job.job_id} failed:\n" + traceback.format_exc())

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
