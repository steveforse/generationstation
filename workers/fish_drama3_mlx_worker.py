"""Fish Audio Drama 3 speech worker for Apple silicon, through mlx-audio (mlx-community/fish-audio-drama-3-3bit).
Runs in the mlx-audio environment, with the model in this process; no WSL and no server.

The script handling is the NVIDIA worker's (fish_drama3_worker.py): speak and scene modes, speaker tags, splitting
long text, voices taken from a sample or from a short take, pauses tidied, takes made again when they come back
incomplete. Only the way a take is made differs. The speech-to-text check is not available here, so takes are
judged by their length and where they end.

Fish Audio Community License v1.0: free use below USD 500,000 annual revenue (You and Your Affiliates); no hosted
services for third parties; no training of other models on the output.

Config options (from runtimes.json, per preset):
    model_dir    The mlx-community/fish-audio-drama-3-3bit folder (the 4-bit one peaks near 26 GiB).
    max_frames   A take's frame limit (about 21.5 frames/s; default 1024).
"""
import io
import os
import random
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import fish_drama3_worker as drama
from gs_worker import serve
from mlx_runtime import MLXThread


class MacServer:
    engine = "mlx"
    checker = None
    speak = drama.Server.speak  # the retry and tidy-up logic, unchanged

    def __init__(self, model, thread, max_frames, log):
        self.model, self.thread, self.max_frames, self.log = model, thread, max_frames, log

    def request(self, text, voices, seed):
        return self.thread.call(lambda: self._take(text, voices, seed))

    def _take(self, text, voices, seed):
        import mlx.core as mx
        import numpy as np
        import soundfile as sf

        kwargs = {"text": text, "max_tokens": self.max_frames}
        if voices:
            kwargs["ref_audio"] = [v["path"] for v in voices]
            kwargs["ref_text"] = [f"<|speaker:{v['speaker']}|> {v['text']}" for v in voices]
        mx.random.seed(seed if seed is not None else random.randrange(1, 2**31))
        pieces, rate = [], 44100
        for part in self.model.generate(**kwargs):
            pieces.append(np.array(part.audio))
            rate = part.sample_rate or rate
        if not pieces:
            raise RuntimeError("The model produced no audio.")
        out = io.BytesIO()
        sf.write(out, np.concatenate(pieces).astype("float32"), rate, format="WAV", subtype="PCM_16")
        return out.getvalue()


def load(config, log=print):
    from mlx_audio.tts.utils import load_model

    options = config["options"]
    thread = MLXThread()
    started = time.perf_counter()
    model = thread.call(lambda: load_model(options["model_dir"]))
    log(f"[worker] Drama 3 ready in {time.perf_counter() - started:.1f} s")
    return {"server": MacServer(model, thread, int(options.get("max_frames", 1024)), lambda m: log(f"[worker] {m}"))}


generate = drama.generate

if __name__ == "__main__":
    serve(load, generate)
