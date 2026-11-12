"""Stand-in for a model worker (gs_worker protocol). Writes a one-second tone; loads no model.

Options: load_delay (seconds), fail_load (bool). Input style "fail" makes the job fail.
"""
import math
import struct
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
from gs_worker import serve


def load(config):
    options = config["options"]
    time.sleep(float(options.get("load_delay", 0.3)))
    if options.get("fail_load"):
        raise RuntimeError("weights not found at C:/models/missing")
    return {"gpus": config["gpus"], "settings": config["settings"]}


def generate(model, inputs, job):
    if inputs.get("style") == "fail":
        raise ValueError("lyrics could not be planned")
    job.report("Writing the melody")
    time.sleep(0.2)
    path = job.output("song.wav", "audio/wav")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 8000)))
                                 for i in range(8000)))
    job.report(f"Done: seed {inputs.get('seed')}")


if __name__ == "__main__":
    serve(load, generate)
