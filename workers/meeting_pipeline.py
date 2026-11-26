"""Speech-to-text for meeting notes, run inside WSL by workers/meeting_notes_worker.py: one process per step, which
loads its model, does the step and exits, so the card is free again when it returns.

    python meeting_pipeline.py diarize  <audio.wav> <turns.json> <diarizen model>
    python meeting_pipeline.py turns    <audio.wav> <turns.json> <segments.json> <qwen3-asr folder> [terms]
    python meeting_pipeline.py nemotron <audio.wav> <segments.json> <socket> [terms]
    python meeting_pipeline.py vibevoice <audio.wav> <segments.json> <vibevoice folder> [terms]
    python meeting_pipeline.py sherpa   <audio.wav> <turns.json> <pyannote segmentation .onnx> <speaker embedding .onnx> [threshold]
    python meeting_pipeline.py mlxturns <audio.wav> <turns.json> <segments.json> <mlx qwen3-asr folder> [terms]
    python meeting_pipeline.py nametags <video> <segments.json> <names.json>

nametags reads the speaker's name off the video (Zoom and Meet print it at the bottom-left of the active speaker's tile)
and needs rapidocr-onnxruntime, Pillow and ffmpeg. It writes {speaker: {"name", "votes", "frames"}} for the speakers it
could name.

The last two run on Apple silicon (engine "mlx" in the worker): sherpa-onnx's pyannote segmentation and a speaker
embedding model on the processor, then Qwen3-ASR on MLX per turn. Neither needs a token or an NVIDIA card.

Every step writes segments as [{"speaker", "start", "end", "text"}] (diarize writes turns without text) and prints one
JSON line {"ok": true, ...stats} or {"ok": false, "error": ...} last. Audio is 16 kHz mono WAV (the worker converts it).

Engines (2026-11-23 bake-off on four AMI meetings, speaker-attributed word error, lower is better): Nemotron 3.5
Transcribe 17.3% (RTX 5090 only: NVFP4 needs Blackwell), Qwen3-ASR-1.7B over DiariZen turns 24.3% (either card),
VibeVoice-ASR 35.1% (merged two speakers in the hardest meeting).
"""
import json
import re
import sys
import time

SHERPA_THRESHOLD = 0.9  # clustering distance: lower splits more speakers, higher merges. A 36-minute Zoom meeting: 0.4 found 59 speakers, 0.75 found 13, 0.9 the 8 (6 real)


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


def sherpa(audio_path, out_path, segmentation, embedding, threshold=SHERPA_THRESHOLD):
    """Speaker turns with sherpa-onnx (pyannote segmentation 3.0 plus a speaker embedding, clustered); no card needed."""
    import os

    import sherpa_onnx
    started = time.time()
    audio = load_audio(audio_path)
    # 36 minutes: 95 s on one thread, 66 s on eight. CoreML (GPU and Neural Engine) was slower, 148-159 s, with the same turns.
    threads = min(8, os.cpu_count() or 1)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=segmentation), num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=embedding, num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=float(threshold)),
        min_duration_on=0.3, min_duration_off=0.5)
    if not config.validate():
        raise RuntimeError("The speaker model files could not be used (check the segmentation and embedding paths).")
    result = sherpa_onnx.OfflineSpeakerDiarization(config).process(audio).sort_by_start_time()
    turns = [{"speaker": str(r.speaker), "start": round(r.start, 3), "end": round(r.end, 3)} for r in result]
    with open(out_path, "w") as f:
        json.dump(turns, f)
    done(seconds=round(time.time() - started, 1), turns=len(turns), speakers=len({t["speaker"] for t in turns}))


def echoes_hotwords(text, hotwords):
    """True when the text is only the hint's own words, joined (which nobody said)."""
    norm = lambda value: re.sub(r"[^a-z0-9]+", "", value.lower())
    words = {norm(w) for w in hotwords}
    parts = [norm(p) for p in re.split(r"[,;]", text) if norm(p)]
    return len(parts) >= 2 and all(p in words for p in parts)


def mlxturns(audio_path, turns_path, out_path, model, terms=""):
    """Qwen3-ASR on MLX over each speaker turn (the same shape as `turns`, without CUDA)."""
    from mlx_audio.stt.utils import load_model
    started = time.time()
    audio = load_audio(audio_path)
    with open(turns_path) as f:
        merged = merge_turns(json.load(f))
    asr = load_model(model)
    hotwords = [t.strip() for t in terms.replace("\n", ",").split(",") if t.strip()] if terms else None
    segs = []
    for turn in merged:
        clip = audio[int(turn["start"] * 16000):int(turn["end"] * 16000)]
        if len(clip) < 1600:  # under 0.1 s: nothing to recognise
            continue
        text = (asr.generate(clip, language="English", hotwords=hotwords, max_tokens=512).text or "").strip()
        if text and hotwords and echoes_hotwords(text, hotwords):
            continue  # on noise the model can say its hint back ("Apollo, ACME, sprint review")
        if text:
            segs.append({"speaker": turn["speaker"], "start": turn["start"], "end": turn["end"], "text": text})
    with open(out_path, "w") as f:
        json.dump(segs, f)
    done(seconds=round(time.time() - started, 1), segments=len(segs))


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


# ----- speaker names from the video ------------------------------------------------------------------------

# Where a name tag sits, as fractions of the frame (left, top, right, bottom). Zoom, 2026-11-25, 3008x1692 recordings:
# while someone shares a screen the active speaker is a small tile at the top-right with its name at the tile's
# bottom-left; in speaker view with nothing shared the tile is the whole frame. Both regions are read for every frame.
NAME_REGIONS = {"tile": (0.86, 0.0, 1.0, 0.13), "frame": (0.0, 0.92, 0.36, 1.0)}
NAME_FRAMES = 10  # frames sampled per speaker, from the middle of their turns
NAME_MIN_VOTES = 3
NAME_MIN_SHARE = 0.5  # of the speaker's frames that showed any name
NAME_MIN_SPECIFIC = 0.3  # of a name's votes, the part that belongs to the speaker it names (on-screen text is everyone's)
NOT_NAMES = {"mute", "unmute", "stop video", "start video", "share", "participants", "chat", "reactions", "leave",
             "end", "record", "zoom", "you", "me", "host", "co-host", "guest", "recording", "view", "more"}


def clean_name(text):
    """The person's name from a tag like "Dana Park| Platform Tea...", "Mira Voss (she/her) | ...", "Dana Park / Platform Team / Product
    Manager" or "Theo Hale | ACME Core | iOS". OCR reads Zoom's "|" as "|", "/", "I", "l" or nothing, so the name is the
    leading words before any of those, a bracket or a word with digits."""
    text = re.sub(r"\([^)]*\)?", " ", text)  # (she/her), (Guest), a cut-off "(she/"
    text = re.split(r"[|/]|\s{2,}|\s[Il]\s|\s[Il]$", text)[0]
    word = r"[^\W\d_](?:[^\W\d_]|['’\-])*\.?"
    tokens = []
    for token in text.replace("…", " ").replace("...", " ").split():
        if not re.fullmatch(word, token):
            break
        tokens.append(token)
    if len(tokens) > 1 and len(tokens[-1]) == 1 and not tokens[-1].endswith("."):
        tokens.pop()  # a stray letter where the "|" was
    name = " ".join(tokens[:4]).rstrip(".")
    if len(name) < 3 or name.lower() in NOT_NAMES:
        return None
    return name


def same_name(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.85


def best_spelling(counts):
    """The most common spelling; where two differ only by a missing space ("IvanCole"), the one with the space."""
    top = max(counts, key=counts.get)
    squeezed = top.replace(" ", "").lower()
    spaced = [name for name in counts if " " in name and name.replace(" ", "").lower() == squeezed]
    return spaced[0] if spaced and " " not in top else top


def choose_names(frames):
    """{speaker: [names seen in each sampled frame]} -> {speaker: {"name", "votes", "frames"}} for those named with
    confidence. Text that stays on screen whoever is talking (a dock, a menu bar) is seen for every speaker, so a name
    is scored by its votes for this speaker times this speaker's share of all its votes; the best must still have
    NAME_MIN_VOTES votes and appear in NAME_MIN_SHARE of the frames that showed any name. Spellings within a typo of
    each other count together (the most common spelling wins)."""
    per_speaker = {}
    for speaker, seen in frames.items():
        seen = [names for names in seen if names]
        groups = []  # one {spelling: count} per distinct name
        for names in seen:
            for name in set(names):
                for group in groups:
                    if any(same_name(name, known) for known in group):
                        group[name] = group.get(name, 0) + 1
                        break
                else:
                    groups.append({name: 1})
        per_speaker[speaker] = (len(seen), groups)
    totals = {}  # votes for each name over all speakers
    for _count, groups in per_speaker.values():
        for group in groups:
            for name, votes in group.items():
                key = next((known for known in totals if same_name(name, known)), name)
                totals[key] = totals.get(key, 0) + votes
    out = {}
    for speaker, (seen_count, groups) in per_speaker.items():
        scored = []
        for group in groups:
            votes = sum(group.values())
            spelling = best_spelling(group)
            overall = totals[next(known for known in totals if same_name(spelling, known))]
            everywhere = len(per_speaker) >= 3 and all(
                any(same_name(spelling, known) and sum(g.values()) >= NAME_MIN_VOTES for g in other for known in g)
                for _c, other in per_speaker.values())
            if votes / overall >= NAME_MIN_SPECIFIC and not everywhere:
                scored.append((votes * votes / overall, len(spelling.split()), votes, spelling))
        if not scored:
            continue
        _score, _words, votes, name = max(scored)
        unanimous = votes >= 2 and votes == seen_count  # a speaker with little to sample: every frame agrees
        if (votes >= NAME_MIN_VOTES or unanimous) and votes / seen_count >= NAME_MIN_SHARE:
            out[speaker] = {"name": name, "votes": votes, "frames": seen_count}
    for speaker, entry in out.items():  # one spelling per person across speakers (the same person split in two, or an OCR typo)
        rivals = [other for other in out.values() if same_name(other["name"], entry["name"])]
        entry["name"] = max(rivals, key=lambda other: other["votes"])["name"]
    return out


def spread(items, count):
    if len(items) <= count:
        return list(items)
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def sample_times(turns_of, count):
    """Moments to look at the video for one speaker: longer turns first, a few points inside each (a name tag is on
    screen for the whole turn), and turns of a second or more when the long ones are too few; spread over the meeting."""
    points = []
    for seg in turns_of:
        length = seg["end"] - seg["start"]
        if length < 1.0:
            continue
        shares = (0.5,) if length < 8 else (1 / 3, 2 / 3) if length < 16 else (0.25, 0.5, 0.75)
        for share in shares:
            points.append((length >= 2.5, seg["start"] + length * share))
    points.sort(key=lambda p: p[1])
    long_ones = [p for p in points if p[0]]
    chosen = spread(long_ones, count)
    if len(chosen) < count:  # few long turns: add the short ones that are left
        extra = [p for p in points if not p[0]]
        chosen += spread(extra, count - len(chosen))
    return sorted(at for _long, at in chosen)


def nametags(video_path, segments_path, out_path, frames_per_speaker=NAME_FRAMES):
    import io
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    started = time.time()
    with open(segments_path) as f:
        segments = json.load(f)
    by_speaker = {}
    for seg in segments:
        by_speaker.setdefault(seg["speaker"], []).append(seg)
    ocr = RapidOCR()

    def grab(at):  # BMP: PNG-encoding a 3008x1692 frame took as long as decoding it
        return subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", video_path,
                               "-frames:v", "1", "-f", "image2pipe", "-vcodec", "bmp", "-"],
                              capture_output=True, timeout=120, check=False).stdout

    plan = [(speaker, at) for speaker, turns_of in by_speaker.items() for at in sample_times(turns_of, frames_per_speaker)]
    seen = {speaker: [] for speaker in by_speaker}
    frames = 0
    with ThreadPoolExecutor(max_workers=4) as pool:  # ffmpeg processes decode ahead of the OCR
        for (speaker, _at), grabbed in zip(plan, pool.map(grab, [at for _speaker, at in plan])):
            if not grabbed:
                continue
            image = Image.open(io.BytesIO(grabbed)).convert("RGB")
            width, height = image.size
            names = set()
            for left, top, right, bottom in NAME_REGIONS.values():
                crop = image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
                crop = crop.resize((crop.width * 2, crop.height * 2))
                found, _ = ocr(np.array(crop))
                for _box, text, confidence in found or []:
                    name = clean_name(text) if float(confidence) >= 0.6 else None
                    if name:
                        names.add(name)
            seen[speaker].append(sorted(names))
            frames += 1
    chosen = choose_names(seen)
    with open(out_path, "w") as f:
        json.dump(chosen, f)
    done(seconds=round(time.time() - started, 1), frames=frames, speakers=len(by_speaker), named=len(chosen))


if __name__ == "__main__":
    step, args = sys.argv[1], sys.argv[2:]
    try:
        {"diarize": diarize, "turns": turns, "nemotron": nemotron, "vibevoice": vibevoice,
         "sherpa": sherpa, "mlxturns": mlxturns, "nametags": nametags}[step](*args)
    except Exception as exc:  # noqa: BLE001 - the worker shows this line
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2000]}), flush=True)
        raise SystemExit(1)
