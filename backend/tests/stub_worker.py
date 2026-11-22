"""Stand-in for a model worker (gs_worker protocol). Writes a one-second tone; loads no model.

Options: load_delay (seconds), fail_load (bool). Input style "fail" makes the job fail; "slow" takes 3 s.
"""
import math
import struct
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
from gs_worker import serve


class TinyImage:
    """Just enough of PIL's Image for Job.thumbnail: writes a fixed 1x1 JPEG."""
    JPEG = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
        "20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f000001050101010101010000"
        "0000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191"
        "a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a"
        "737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8"
        "d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9")

    def convert(self, mode):
        return self

    def thumbnail(self, size):
        pass

    def save(self, path, quality=None):
        Path(path).write_bytes(self.JPEG)


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
    if inputs.get("style") == "slow":  # 3 s in steps, so a cancel takes effect at the next one
        job.output("partial.wav", "audio/wav").write_bytes(b"RIFF")
        (job.dir / "inputs").mkdir(exist_ok=True)
        (job.dir / "inputs" / "01-given.png").write_bytes(b"x")
        for step in range(30):
            time.sleep(0.1)
            job.report(f"Composing, step {step + 1} of 30")
    else:
        time.sleep(0.2)
    path = job.output("song.wav", "audio/wav")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 8000)))
                                 for i in range(8000)))
    job.detail(seed=inputs.get("seed"), prompt=f"style: {inputs.get('style')}")
    if inputs.get("style") == "picture":  # exercises the thumbnail helper with a tiny stand-in image
        job.thumbnail(TinyImage())
    job.report(f"Done: seed {inputs.get('seed')}")


if __name__ == "__main__":
    serve(load, generate)
