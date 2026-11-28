"""Generation jobs: validate a request, hand it to the model's worker, and track it to its files."""
import shutil
import uuid
from pathlib import Path

from .lifecycle import LifecycleError
from .runtimes import SettingsError, validate_inputs

TERMINAL = {"done", "failed", "cancelled"}
INPUTS_FOLDER = "inputs"  # a job's copies of its uploaded files, inside its output folder


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_job(job):
    return {"id": job["id"], "model_id": job["model_id"], "inputs": job["inputs"], "status": job["status"],
            "progress": job.get("progress"), "outputs": job.get("outputs") or [],
            "error_message": job.get("error_message"), "created_at": _iso(job["created_at"]),
            "finished_at": _iso(job.get("finished_at")), "details": job.get("details") or {},
            "launch": job.get("launch")}


class GenerationManager:
    def __init__(self, store, catalog, uploads=None):
        self.store = store
        self.catalog = catalog
        self.uploads = uploads

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
            values = validate_inputs(plugin, inputs, self.uploads.get if self.uploads else None, runtime)
        except SettingsError as exc:
            raise LifecycleError("INPUTS_INVALID", " ".join(exc.errors), 422,
                                 resources=[{"error": e} for e in exc.errors]) from exc
        job_id = str(uuid.uuid4())
        values, worker_values = self._attach_files(plugin, runtime, job_id, values)
        try:
            plugin.submit(runtime, job_id, worker_values)
        except RuntimeError as exc:
            shutil.rmtree(Path(plugin.output_dir(runtime)) / job_id, ignore_errors=True)
            raise LifecycleError("WORKER_UNAVAILABLE", f"{runtime.name} could not take the job: {exc}", 503) from exc
        operation = self.store.get_operation(state["active_operation_id"]) if state.get("active_operation_id") else None
        job = self.store.create_job(job_id=job_id, model_id=model_id,
                                    load_operation_id=state.get("active_operation_id"), inputs=values,
                                    launch=(operation or {}).get("launch"))
        return serialize_job(job)

    def _attach_files(self, plugin, runtime, job_id, values):
        """Copy a request's uploads into the job's own folder. The stored inputs name the copies; the
        worker's inputs also carry their paths."""
        specs = plugin.mode_inputs(values.get("mode"), runtime)
        stored, worker = dict(values), dict(values)
        folder = Path(plugin.output_dir(runtime)) / job_id / INPUTS_FOLDER
        index = 0
        for key, spec in specs.items():
            if spec.kind != "files" or key not in values:
                continue
            stored[key], worker[key] = [], []
            for upload_id in values[key]:
                record = self.uploads.get(upload_id)
                index += 1
                name = self.uploads.copy_to(record, folder, index)
                entry = {"name": name, "kind": record["kind"], "mime": record["mime"], "original": record["name"]}
                stored[key].append(entry)
                worker[key].append({**entry, "path": str(folder / name)})
        return stored, worker

    def input_path(self, job_id, name):
        """A file attached to a job's request (a reference picture, video or audio)."""
        job = self.store.get_job(job_id)
        runtime = self.catalog.runtimes.get(job["model_id"]) if job else None
        if job is None or runtime is None:
            raise LifecycleError("JOB_NOT_FOUND", "That file is not available.", 404)
        entry = next((item for value in job["inputs"].values() if isinstance(value, list)
                      for item in value if isinstance(item, dict) and item.get("name") == name), None)
        root = (Path(self.catalog.plugin(job["model_id"]).output_dir(runtime)) / job_id / INPUTS_FOLDER).resolve()
        path = (root / name).resolve()
        if entry is None or path.parent != root or not path.is_file():
            raise LifecycleError("JOB_NOT_FOUND", "That file is not available.", 404)
        return path, entry.get("mime") or "application/octet-stream"

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
        if status not in {"queued", "running", "done", "failed", "cancelled"}:
            return job
        outputs = [{"name": o.get("name"), "mime": o.get("mime"), "bytes": o.get("bytes")}
                   for o in record.get("outputs") or [] if isinstance(o, dict)]
        details = record.get("details") if isinstance(record.get("details"), dict) else None
        if (status, record.get("progress"), outputs, details or None) == (
                job["status"], job.get("progress"), job.get("outputs"), job.get("details") or None):
            return job
        return self.store.update_job(job["id"], status=status, progress=record.get("progress"),
                                     outputs=outputs if status == "done" else None,
                                     error_message=record.get("error"), details=details)

    def get(self, job_id):
        job = self.store.get_job(job_id)
        if job is None:
            raise LifecycleError("JOB_NOT_FOUND", "That job does not exist.", 404)
        return serialize_job(self._refresh(job))

    def list(self, model_id=None, limit=50):
        return {"jobs": [serialize_job(self._refresh(job)) for job in self.store.list_jobs(model_id, limit)]}

    def cancel(self, job_id):
        """Cancel a queued job at once, or a running one at its next step (it shows "Cancelling" until then)."""
        job = self.store.get_job(job_id)
        if job is None:
            raise LifecycleError("JOB_NOT_FOUND", "That job does not exist.", 404)
        job = self._refresh(job)
        if job["status"] in TERMINAL:
            raise LifecycleError("JOB_FINISHED", "This has already finished.", 409)
        runtime = self.catalog.runtimes.get(job["model_id"])
        record = self.catalog.plugin(job["model_id"]).cancel(runtime, job_id) if runtime is not None else {"status": "missing"}
        if record is None:
            raise LifecycleError("WORKER_UNAVAILABLE", "The model did not accept the cancel. If it was started before "
                                 "cancelling existed, stop and start it once.", 503)
        if record.get("status") == "missing":  # the worker never had it or has restarted
            return serialize_job(self.store.update_job(job_id, status="cancelled", progress="Cancelled"))
        return serialize_job(self.store.update_job(job_id, status=record.get("status", job["status"]),
                                                   progress=record.get("progress")))

    def delete(self, job_id):
        """Delete a finished job: its record and its folder of files. Running jobs cannot be deleted."""
        job = self.store.get_job(job_id)
        if job is None:
            raise LifecycleError("JOB_NOT_FOUND", "That job does not exist.", 404)
        job = self._refresh(job)
        if job["status"] not in TERMINAL:
            raise LifecycleError("JOB_RUNNING", "This is still being made. Delete it once it has finished.", 409)
        runtime = self.catalog.runtimes.get(job["model_id"])
        if runtime is not None:
            root = Path(self.catalog.plugin(job["model_id"]).output_dir(runtime)).resolve()
            folder = (root / job_id).resolve()
            if folder.parent == root and folder.is_dir():
                shutil.rmtree(folder)
        self.store.delete_job(job_id)
        return {"id": job_id, "deleted": True}

    def edit_transcript(self, job_id, payload):
        """Correct a finished meeting's transcript (speakers and words). Only plugins that offer it (meeting notes) do."""
        return self._edit_meeting(job_id, payload, "edit_transcript", "transcript")

    def edit_notes(self, job_id, payload):
        """Replace a finished meeting's summary, action items or decisions. Only plugins that offer it do."""
        return self._edit_meeting(job_id, payload, "edit_notes", "notes")

    def _edit_meeting(self, job_id, payload, method, what):
        job = self.store.get_job(job_id)
        runtime = self.catalog.runtimes.get(job["model_id"]) if job else None
        edit = getattr(self.catalog.plugin(job["model_id"]), method, None) if runtime else None
        if job is None or runtime is None or job["status"] != "done" or edit is None:
            raise LifecycleError("JOB_NOT_FOUND", f"There are no {what} to edit here.", 404)
        root = Path(self.catalog.plugin(job["model_id"]).output_dir(runtime)).resolve()
        folder = (root / job_id).resolve()
        if folder.parent != root or not folder.is_dir():
            raise LifecycleError("JOB_NOT_FOUND", f"There are no {what} to edit here.", 404)
        try:
            return edit(folder, payload)
        except ValueError as exc:  # TranscriptEditError
            raise LifecycleError(getattr(exc, "code", "TRANSCRIPT_INVALID"), str(exc), getattr(exc, "status", 422)) from exc

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
