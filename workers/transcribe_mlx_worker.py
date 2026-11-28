"""Speech-to-text worker for Apple silicon, through mlx-audio. Runs in the mlx-audio environment. One worker, three models: the
`engine` option picks the one this preset loads.

    qwen3_asr   Qwen3-ASR 1.7B (8-bit). Cut into 30 second parts at pauses: whole recordings in one go loop and repeat.
    whisper     Whisper large-v3-turbo. Windows of 30 seconds with times; 99 languages.
    parakeet    Parakeet TDT v3. 60 second parts that overlap by 2 seconds; 25 European languages, detected.

Config options (from runtimes.json, per preset):
    engine, model_dir
    diar_python, segmentation_model, embedding_model, diar_threshold   Optional: "who spoke" for the models that do not label
        speakers themselves, with the speaker turns the meeting notes use (sherpa-onnx, run in the environment diar_python).

Inputs: recording ([{"path"}], audio or video), split ("fewer" | "usual" | "more": how readily voices are told apart), language ("auto" or a name; Qwen3-ASR and Whisper), terms (names and words to
expect; not Parakeet), speakers ("yes" or "no").
Outputs: transcript.md, transcript.txt, transcript.json, and transcript.srt and transcript.vtt when the model gives times.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import transcript_files
from gs_worker import serve
from meeting_pipeline import echoes_hotwords, merge_turns
from mlx_runtime import MLXThread

SAMPLE_RATE = 16000
# Language names the form offers, and the codes Whisper takes (Qwen3-ASR takes the names).
WHISPER_CODES = {"English": "en", "Spanish": "es", "French": "fr", "German": "de", "Italian": "it", "Portuguese": "pt", "Dutch": "nl", "Polish": "pl",
                 "Russian": "ru", "Japanese": "ja", "Korean": "ko", "Chinese": "zh", "Arabic": "ar", "Hindi": "hi", "Turkish": "tr",
                 "Vietnamese": "vi", "Swedish": "sv", "Czech": "cs", "Greek": "el"}
MIMES = {"transcript.md": "text/markdown", "transcript.txt": "text/plain", "transcript.srt": "application/x-subrip", "transcript.vtt": "text/vtt"}
ENGINES = ("qwen3_asr", "whisper", "parakeet")


def load(config, log=print):
    from mlx_audio.stt.utils import load_model

    options = config["options"]
    engine = options.get("engine")
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {', '.join(ENGINES)}")
    thread = MLXThread()
    started = time.perf_counter()
    model = thread.call(lambda: load_model(options["model_dir"]))
    log(f"[worker] {engine} ready in {time.perf_counter() - started:.1f} s")
    return {"model": model, "thread": thread, "options": options, "engine": engine}


def terms_of(text):
    return [term.strip() for term in (text or "").replace("\n", ",").split(",") if term.strip()]


def to_wav(recording, folder):
    """The recording's sound as 16 kHz mono, and its length in seconds."""
    wav = Path(folder) / "audio.wav"
    done = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", recording, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), str(wav)],
                          capture_output=True, text=True)
    if done.returncode != 0 or not wav.exists():
        lines = done.stderr.strip().splitlines()
        raise ValueError("That file could not be read as audio or video" + (f": {lines[-1][:200]}" if lines else "."))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)], capture_output=True, text=True)
    seconds = float(probe.stdout.strip() or 0)
    if seconds < 0.2:
        raise ValueError("That file has no sound to write down.")
    return wav, seconds


SPLIT_SHIFT = {"fewer": 0.15, "usual": 0.0, "more": -0.2}  # added to the clustering distance: lower splits voices more


def speaker_turns(options, wav, folder, split="usual"):
    """Who spoke when: the sherpa-onnx turns of the meeting notes, as [{speaker, start, end}]."""
    if not options.get("segmentation_model"):
        raise ValueError("Speaker detection is not set up on this computer.")
    out = Path(folder) / "turns.json"
    pipeline = Path(__file__).with_name("meeting_pipeline.py")
    done = subprocess.run([options.get("diar_python") or sys.executable, str(pipeline), "sherpa", str(wav), str(out), options["segmentation_model"],
                           options["embedding_model"], str(round(float(options.get("diar_threshold", 0.9)) + SPLIT_SHIFT.get(split, 0.0), 2))], capture_output=True, text=True)
    if done.returncode != 0 or not out.exists():
        lines = done.stdout.strip().splitlines() or done.stderr.strip().splitlines()
        raise RuntimeError("Finding the speakers failed" + (f": {lines[-1][:300]}" if lines else "."))
    return json.loads(out.read_text())


def timed(items, start="start", end="end", text="text"):
    return [{"start": float(item[start]), "end": float(item[end]), "text": item[text].strip()} for item in items if item[text].strip()]


def run_qwen(state, wav, inputs, terms, turns, job):
    import soundfile

    asr = state["model"]
    language = inputs.get("language") if inputs.get("language") not in (None, "", "auto") else None
    if turns is None:
        out = asr.generate(str(wav), language=language, chunk_duration=30, hotwords=terms or None, max_tokens=1024)
        return timed(out.segments or [{"start": 0, "end": 0, "text": out.text}]), (out.language[0] if isinstance(out.language, list) else out.language)
    audio, _ = soundfile.read(str(wav), dtype="float32")
    parts = merge_turns(turns)
    segments = []
    for number, turn in enumerate(parts, 1):
        job.report(f"Listening, part {number} of {len(parts)}")
        clip = audio[int(turn["start"] * SAMPLE_RATE):int(turn["end"] * SAMPLE_RATE)]
        if len(clip) < SAMPLE_RATE // 10:
            continue
        said = (asr.generate(clip, language=language, hotwords=terms or None, max_tokens=512).text or "").strip()
        if said and not (terms and echoes_hotwords(said, terms)):  # on noise the model can say its hint back
            segments.append({"speaker": turn["speaker"], "start": turn["start"], "end": turn["end"], "text": said})
    return segments, language


def run_whisper(state, wav, inputs, terms, job):
    language = WHISPER_CODES.get(inputs.get("language") or "")
    out = state["model"].generate(str(wav), language=language, initial_prompt=", ".join(terms) if terms else None)
    return timed(out.segments or [{"start": 0, "end": 0, "text": out.text}]), out.language


def run_parakeet(state, wav, inputs, terms, job):
    out = state["model"].generate(str(wav), chunk_duration=60.0, overlap_duration=2.0)
    sentences = getattr(out, "sentences", None) or []
    if sentences:
        return [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in sentences if s.text.strip()], None
    return [{"text": out.text.strip()}], None


def transcribe(state, inputs, job, folder):
    engine, options = state["engine"], state["options"]
    terms = terms_of(inputs.get("terms"))
    speakers = inputs.get("speakers") == "yes"
    job.report("Preparing the audio")
    wav, seconds = to_wav(inputs["recording"][0]["path"], folder)
    turns = None
    if speakers:
        job.report("Finding who spoke")
        turns = speaker_turns(options, wav, folder, inputs.get("split") or "usual")
    if job.cancel_requested:
        job.report("Cancelling")
    job.report("Listening")

    def work():
        if engine == "qwen3_asr":
            return run_qwen(state, wav, inputs, terms, turns, job)
        if engine == "whisper":
            return run_whisper(state, wav, inputs, terms, job)
        return run_parakeet(state, wav, inputs, terms, job)

    segments, language = state["thread"].call(work)
    if turns is not None and engine != "qwen3_asr":
        segments = transcript_files.assign_speakers(segments, turns)
    if speakers:
        segments = transcript_files.merge_same_speaker(transcript_files.name_speakers(segments))
    if not any(segment.get("text") for segment in segments):
        raise ValueError("No speech was found in that recording.")
    return segments, language, seconds


def generate(state, inputs, job):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="gs-asr-") as folder:
        segments, language, audio_seconds = transcribe(state, inputs, job, folder)
    job.report("Writing the transcript")
    files = transcript_files.render(segments)
    for name, text in files.items():
        job.output(name, MIMES[name]).write_text(text, encoding="utf-8")
    text = " ".join(segment["text"] for segment in segments)
    record = {"engine": state["engine"], "language": language or inputs.get("language") or "auto", "audio_seconds": round(audio_seconds, 1),
              "terms": terms_of(inputs.get("terms")), "text": text, "segments": segments}
    job.output("transcript.json", "application/json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    speakers = len({segment["speaker"] for segment in segments if segment.get("speaker")})
    job.detail(engine=state["engine"], audio_seconds=round(audio_seconds, 1), words=len(text.split()), language=record["language"],
               **({"speakers": speakers} if speakers else {}), times="yes" if "transcript.srt" in files else "no")
    job.report(f"Done in {time.perf_counter() - started:.0f} s: {len(text.split())} words from {audio_seconds / 60:.1f} minutes of audio")


if __name__ == "__main__":
    serve(load, generate)
