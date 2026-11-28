"""Write down what a voice sample says, so the form can pre-fill "what the sample says".

Runs `workers/transcribe_cli.py` once per request in the Python environment of a speech model that has a transcriber folder
(`asr_dir` in its preset options, the Qwen3-ASR the cloning workers already use). One request at a time; a model that has no
transcriber set up is refused, and the page then leaves the field for the person to type.
"""
import json
import subprocess
import threading
from pathlib import Path

from .plugins.worker import WORKERS_DIR

TIMEOUT_SECONDS = 180
MAX_CHARS = 1000


class TranscribeError(ValueError):
    pass


def _run(argv, env, timeout):
    return subprocess.run(argv, env=env, cwd=str(WORKERS_DIR), capture_output=True, text=True, timeout=timeout, check=False).stdout


class Transcriber:
    def __init__(self, catalog, uploads, run=_run):
        self.catalog, self.uploads, self.run = catalog, uploads, run
        self.lock = threading.Lock()

    def folder(self, model_id: str) -> tuple[str, str]:
        """(python, transcriber folder) of a speech model, or TranscribeError."""
        runtime = self.catalog.runtimes.get(model_id)
        if runtime is None:
            raise LookupError("There is no such model.")
        python = getattr(runtime, "python", None)
        folder = next((preset.options["asr_dir"] for preset in getattr(runtime, "presets", {}).values()
                       if isinstance(getattr(preset, "options", None), dict) and preset.options.get("asr_dir")), None)
        if runtime.workload != "speech" or not python or not folder:
            raise TranscribeError(f"{runtime.name} has no transcriber set up.")
        return python, str(folder)

    def transcribe(self, model_id: str, upload_id: str, language: str = "English") -> str:
        python, folder = self.folder(model_id)
        record = self.uploads.get(upload_id)
        if not record or record.get("kind") != "audio":
            raise TranscribeError("That sample was not found. Add it again.")
        env = {"PYTHONPATH": str(WORKERS_DIR), "PYTHONUNBUFFERED": "1", "HOME": str(Path.home()), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        argv = [python, str(WORKERS_DIR / "transcribe_cli.py"), folder, str(self.uploads.root / record["file"]), language]
        with self.lock:
            try:
                out = self.run(argv, env, TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TranscribeError("The transcriber could not be run.") from exc
        try:
            answer = json.loads(out.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise TranscribeError("The transcriber gave no answer.") from exc
        if not isinstance(answer, dict) or "text" not in answer:
            raise TranscribeError("The sample could not be transcribed.")
        return " ".join(str(answer["text"]).split())[:MAX_CHARS]
