"""Helpers shared by the Apple-silicon (MLX) workers.

MLX's GPU stream belongs to the thread that created it, and gs_worker loads the model in one thread and runs jobs in
another. `MLXThread` is one long-lived thread that does all the MLX work: tasks go in, results (or the error) come back.
"""
import queue
import threading


class MLXThread:
    def __init__(self):
        self.tasks = queue.Queue()
        threading.Thread(target=self._run, daemon=True, name="mlx").start()

    def _run(self):
        while True:
            task, box, done = self.tasks.get()
            try:
                box["value"] = task()
            except BaseException as exc:  # noqa: BLE001 - handed back to the caller
                box["error"] = exc
            done.set()

    def call(self, task):
        box, done = {}, threading.Event()
        self.tasks.put((task, box, done))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("value")


def transcribe(asr_dir, path, language="English"):
    """The words spoken in an audio file, with an mlx-audio speech model (Qwen3-ASR). Call on the MLX thread."""
    from mlx_audio.stt.utils import load_model

    return (load_model(asr_dir).generate(str(path), language=language, max_tokens=512).text or "").strip()


def write_wav(path, audio, rate):
    import numpy as np
    import soundfile as sf

    sf.write(str(path), np.asarray(audio, dtype="float32"), rate)
