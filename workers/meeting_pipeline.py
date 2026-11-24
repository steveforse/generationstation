"""Speech-to-text for meeting notes, run inside WSL by workers/meeting_notes_worker.py: one process per step, which
loads its model, does the step and exits, so the card is free again when it returns.

    python meeting_pipeline.py diarize  <audio.wav> <turns.json> <diarizen model>
    python meeting_pipeline.py turns    <audio.wav> <turns.json> <segments.json> <qwen3-asr folder> [terms]
    python meeting_pipeline.py nemotron <audio.wav> <segments.json> <socket> [terms]
    python meeting_pipeline.py vibevoice <audio.wav> <segments.json> <vibevoice folder> [terms]

Every step writes segments as [{"speaker", "start", "end", "text"}] (diarize writes turns without text) and prints one
JSON line {"ok": true, ...stats} or {"ok": false, "error": ...} last. Audio is 16 kHz mono WAV (the worker converts it).

Engines (2026-11-23 bake-off on four AMI meetings, speaker-attributed word error, lower is better): Nemotron 3.5
Transcribe 17.3% (RTX 5090 only: NVFP4 needs Blackwell), Qwen3-ASR-1.7B over DiariZen turns 24.3% (either card),
VibeVoice-ASR 35.1% (merged two speakers in the hardest meeting).
"""
import json
import sys
import time


def done(**stats):
    print(json.dumps({"ok": True, **stats}), flush=True)


def load_audio(path):
    import soundfile as sf
    audio, rate = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        raise ValueError(f"expected 16 kHz audio, got {rate}")
    return audio


def peak_gib():
    import torch
    return round(torch.cuda.max_memory_allocated() / 2**30, 2) if torch.cuda.is_available() else 0.0


def diarize(audio_path, out_path, model):
    import torch
    from pyannote.audio.core.task import Problem, Resolution, Specifications
    # DiariZen's checkpoint stores these classes; allow exactly them (torch >= 2.6 loads weights only).
    torch.serialization.add_safe_globals([torch.torch_version.TorchVersion, Specifications, Problem, Resolution])
    from diarizen.pipelines.inference import DiariZenPipeline
    started = time.time()
    pipe = DiariZenPipeline.from_pretrained(model)
    result = pipe(audio_path)
    turns = [{"speaker": str(spk), "start": round(seg.start, 3), "end": round(seg.end, 3)}
             for seg, _, spk in result.itertracks(yield_label=True)]
    with open(out_path, "w") as f:
        json.dump(turns, f)
    done(seconds=round(time.time() - started, 1), turns=len(turns), speakers=len({t["speaker"] for t in turns}),
         peak_gib=peak_gib())


def merge_turns(raw, max_len=30.0, gap=0.5):
    """A speaker's turns merged across short pauses and cut at max_len seconds (what the recogniser takes at once)."""
    out = []
    for t in sorted(raw, key=lambda t: t["start"]):
        last = out[-1] if out else None
        if last and last["speaker"] == t["speaker"] and t["start"] - last["end"] < gap and t["end"] - last["start"] <= max_len:
            last["end"] = max(last["end"], t["end"])
            continue
        s = t["start"]
        while t["end"] - s > max_len:
            out.append({"speaker": t["speaker"], "start": s, "end": s + max_len})
            s += max_len
        out.append({"speaker": t["speaker"], "start": s, "end": t["end"]})
    return out


def turns(audio_path, turns_path, out_path, model, terms=""):
    import torch
    from qwen_asr import Qwen3ASRModel
    started = time.time()
    audio = load_audio(audio_path)
    with open(turns_path) as f:
        merged = merge_turns(json.load(f))
    asr = Qwen3ASRModel.from_pretrained(model, dtype=torch.bfloat16, device_map="cuda:0",
                                        max_inference_batch_size=16, max_new_tokens=512)
    clips, keep = [], []
    for i, t in enumerate(merged):
        clip = audio[int(t["start"] * 16000):int(t["end"] * 16000)]
        if len(clip) >= 1600:  # under 0.1 s: nothing to recognise
            clips.append((clip, 16000)); keep.append(i)
    kwargs = {"context": [terms] * len(clips)} if terms else {}
    try:
        texts = [r.text for r in asr.transcribe(audio=clips, language=["English"] * len(clips), **kwargs)]
    except TypeError:  # a qwen-asr without context support
        texts = [r.text for r in asr.transcribe(audio=clips, language=["English"] * len(clips))]
    segs = [{"speaker": merged[i]["speaker"], "start": merged[i]["start"], "end": merged[i]["end"], "text": t.strip()}
            for i, t in zip(keep, texts) if t.strip()]
    with open(out_path, "w") as f:
        json.dump(segs, f)
    done(seconds=round(time.time() - started, 1), segments=len(segs), peak_gib=peak_gib())


NEMOTRON_PROMPT = ("Transcribe this audio with punctuation and capitalization. Include all spoken words and verbal fillers. "
                   "Write numbers in their standard written form. Put speaker tags <spk:0> <spk:1> <spk:2> <spk:3> on the transcription.")


def nemotron(audio_path, out_path, socket_path, terms=""):
    """Ask a running Nemotron vLLM server (on a Unix socket; see meeting_notes_worker.py) for words, speakers and times."""
    import base64

    import httpx
    started = time.time()
    with open(audio_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    prompt = NEMOTRON_PROMPT + (f" Context terms: {terms}." if terms else "")
    body = {"model": "nemotron", "temperature": 0, "top_p": 1.0, "max_tokens": 32768,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt},
                                                      {"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{data}"}}]}],
            "chat_template_kwargs": {"enable_thinking": False}, "skip_special_tokens": False,
            "spaces_between_special_tokens": False, "seed": 0, "mm_processor_kwargs": {"capture_ctc_timestamps": True}}
    with httpx.Client(transport=httpx.HTTPTransport(uds=socket_path), timeout=3600) as client:
        response = client.post("http://localhost/v1/chat/completions", json=body)
    response.raise_for_status()
    result = response.json()
    ts = result.get("ctc_timestamps") or {}
    if ts.get("error"):
        raise RuntimeError(f"Nemotron could not align its transcript: {ts['error']}")
    segs, cur = [], None
    for w in ts.get("words") or []:  # consecutive words of one speaker become one segment
        spk = str(w.get("speaker"))
        if cur and cur["speaker"] == spk and w["start"] - cur["end"] < 1.0:
            cur["text"] += " " + w["word"]; cur["end"] = w["end"]
        else:
            cur = {"speaker": spk, "start": w["start"], "end": w["end"], "text": w["word"]}
            segs.append(cur)
    with open(out_path, "w") as f:
        json.dump(segs, f)
    done(seconds=round(time.time() - started, 1), segments=len(segs),
         completion_tokens=(result.get("usage") or {}).get("completion_tokens"))


def vibevoice(audio_path, out_path, model, terms=""):
    import torch
    from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration
    started = time.time()
    processor = AutoProcessor.from_pretrained(model)
    asr = VibeVoiceAsrForConditionalGeneration.from_pretrained(model, dtype=torch.bfloat16, device_map="cuda:0")
    kwargs = {"prompt": terms} if terms else {}
    inputs = processor.apply_transcription_request(audio=audio_path, **kwargs).to(asr.device, asr.dtype)
    out = asr.generate(**inputs, max_new_tokens=32768, do_sample=False)
    parsed = processor.decode(out[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]
    if isinstance(parsed, str):
        raise RuntimeError("VibeVoice's answer could not be read as a transcript")  # noqa: TRY004 - a model failure
    segs = [{"speaker": str(p.get("Speaker")), "start": float(p.get("Start") or 0), "end": float(p.get("End") or 0),
             "text": (p.get("Content") or "").strip()}
            for p in parsed if p.get("Speaker") is not None and (p.get("Content") or "").strip()]
    with open(out_path, "w") as f:
        json.dump(segs, f)
    done(seconds=round(time.time() - started, 1), segments=len(segs), peak_gib=peak_gib())


if __name__ == "__main__":
    step, args = sys.argv[1], sys.argv[2:]
    try:
        {"diarize": diarize, "turns": turns, "nemotron": nemotron, "vibevoice": vibevoice}[step](*args)
    except Exception as exc:  # noqa: BLE001 - the worker shows this line
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2000]}), flush=True)
        raise SystemExit(1)
