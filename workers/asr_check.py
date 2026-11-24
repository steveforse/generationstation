"""A small speech-to-text helper: reads WAV paths on stdin (one JSON object per line) and writes their transcripts.

Used by the Drama 3 worker to check that a take says all of its text before keeping it. Runs on the CPU (the speech
card is full while Drama 3 runs), in an environment that has transformers and soundfile (OmniVoice's), with a small
Whisper model (openai/whisper-base.en: about 1 s for 15 s of speech on the desktop's CPU).

    python asr_check.py <whisper model folder>
    stdin:  {"path": "C:\\...\\take.wav"}
    stdout: {"ready": true} once, then {"text": "..."} or {"error": "..."} per request
"""
import json
import sys


def main():
    import soundfile
    import torch
    from transformers import pipeline

    asr = pipeline("automatic-speech-recognition", model=sys.argv[1], device="cpu", torch_dtype=torch.float32)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            audio, rate = soundfile.read(json.loads(line)["path"], dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            text = asr({"raw": audio, "sampling_rate": rate})["text"]
            print(json.dumps({"text": text}), flush=True)
        except Exception as exc:  # noqa: BLE001 - report it and keep serving
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
