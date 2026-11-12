"""Generation jobs: validate a request, hand it to the model's worker, and track it to its files."""
import uuid
from pathlib import Path

from .lifecycle import LifecycleError
from .runtimes import SettingsError, validate_inputs

TERMINAL = {"done", "failed"}


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_job(job):
    return {"id": job["id"], "model_id": job["model_id"], "inputs": job["inputs"], "status": job["status"],
            "progress": job.get("progress"), "outputs": job.get("outputs") or [],
            "error_message": job.get("error_message"), "created_at": _iso(job["created_at"]),
            "finished_at": _iso(job.get("finished_at"))}


class GenerationManager:
    def __init__(self, store, catalog):
        self.store = store
        self.catalog = catalog

    def _runtime(self, model_id):
        runtime = self.catalog.runtimes.get(model_id)
        if runtime is None:
            raise LifecycleError("MODEL_NOT_FOUND", "No configured model has that ID.", 404)
        plugin = self.catalog.plugin(model_id)
        if not plugin.generates:
            raise LifecycleError("NOT_A_GENERATOR", f"{runtime.name} does not make files.", 422)
        return runtime, plugin

    def create(self, model_id, inputs):
        runtime, plugin = self._runtime(model_id)
        state = self.store.runtime_states().get(model_id, {})
        if state.get("state") != "ready":
            raise LifecycleError("MODEL_NOT_READY", f"Start {runtime.name} first, then try again.", 409)
        try:
            values = validate_inputs(plugin, inputs)
        except SettingsError as exc:
            raise LifecycleError("INPUTS_INVALID", " ".join(exc.errors), 422,
                                 resources=[{"error": e} for e in exc.errors]) from exc
        job_id = str(uuid.uuid4())
        try:
            plugin.submit(runtime, job_id, values)
        except RuntimeError as exc:
            raise LifecycleError("WORKER_UNAVAILABLE", f"{runtime.name} could not take the job: {exc}", 503) from exc
        job = self.store.create_job(job_id=job_id, model_id=model_id,
                                    load_operation_id=state.get("active_operation_id"), inputs=values)
        return serialize_job(job)

    def _refresh(self, job):
        if job["status"] in TERMINAL:
            return job
        runtime = self.catalog.runtimes.get(job["model_id"])
        if runtime is None:
            return self.store.update_job(job["id"], status="failed",
                                         error_message="This model is no longer configured.")
        plugin = self.catalog.plugin(job["model_id"])
        state = self.store.runtime_states().get(job["model_id"], {})
        record = plugin.job_status(runtime, job["id"]) if state.get("state") == "ready" else None
        if record is None:
            if state.get("state") == "ready" and state.get("active_operation_id") == job.get("load_operation_id"):
                return job  # the worker is briefly not answering; keep waiting
            return self.store.update_job(job["id"], status="failed",
                                         error_message=f"{runtime.name} stopped before this finished.")
        status = record.get("status")
        if status not in {"queued", "running", "done", "failed"}:
            return job
        outputs = [{"name": o.get("name"), "mime": o.get("mime"), "bytes": o.get("bytes")}
                   for o in record.get("outputs") or [] if isinstance(o, dict)]
        if (status, record.get("progress"), outputs) == (job["status"], job.get("progress"), job.get("outputs")):
            return job
        return self.store.update_job(job["id"], status=status, progress=record.get("progress"),
                                     outputs=outputs if status == "done" else None,
                                     error_message=record.get("error"))

    def get(self, job_id):
        job = self.store.get_job(job_id)
        if job is None:
            raise LifecycleError("JOB_NOT_FOUND", "That job does not exist.", 404)
        return serialize_job(self._refresh(job))

    def list(self, model_id=None, limit=50):
        return {"jobs": [serialize_job(self._refresh(job)) for job in self.store.list_jobs(model_id, limit)]}

    def output_path(self, job_id, name):
        job = self.store.get_job(job_id)
        if job is None or job["status"] != "done":
            raise LifecycleError("JOB_NOT_FOUND", "That file is not available.", 404)
        output = next((o for o in job["outputs"] if o.get("name") == name), None)
        runtime = self.catalog.runtimes.get(job["model_id"])
        if output is None or runtime is None:
            raise LifecycleError("JOB_NOT_FOUND", "That file is not available.", 404)
        root = Path(self.catalog.plugin(job["model_id"]).output_dir(runtime)).resolve()
        path = (root / job_id / name).resolve()
        if root not in path.parents or not path.is_file():
            raise LifecycleError("JOB_NOT_FOUND", "That file is not available.", 404)
        return path, output.get("mime") or "application/octet-stream"
