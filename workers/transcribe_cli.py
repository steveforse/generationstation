"""Write down what is said in one audio file, in the speech models' own environment (mlx-audio and Qwen3-ASR).

    python transcribe_cli.py <qwen3-asr folder> <audio file> [language]

Prints one JSON line: {"text": "..."} or {"error": "..."}. The host runs it to pre-fill "what the sample says" for a voice sample.
"""
import json
import sys


def main():
    try:
        from mlx_runtime import transcribe

        print(json.dumps({"text": transcribe(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "English")}))
    except Exception as exc:  # noqa: BLE001 - reported to the host as the answer
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    main()
