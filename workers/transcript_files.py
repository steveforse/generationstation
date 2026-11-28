"""Turning what a speech-to-text model said into transcript files (pure Python, no model needed).

A segment is {"text", "start"?, "end"?, "speaker"?}: `start` and `end` (seconds) are there for models that give times, and `speaker`
is a label such as "Speaker 1" when the person asked who spoke. `render` writes the files a result offers: transcript.md (readable),
transcript.txt (plain), transcript.srt and transcript.vtt (captions, only when every segment has times).
"""
import re

from meeting_transcript import mmss, srt_time

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def paragraphs(text, sentences=4):
    """A run of text with no times as paragraphs of a few sentences, so a long transcript can be read."""
    parts = [part for part in SENTENCE_END.split(text.strip()) if part]
    return [" ".join(parts[i:i + sentences]) for i in range(0, len(parts), sentences)]


def name_speakers(segments):
    """Give each speaker a label in order of first appearance: Speaker 1, Speaker 2, ... Returns new segments."""
    names, out = {}, []
    for segment in segments:
        who = segment.get("speaker")
        if who is not None:
            names.setdefault(who, f"Speaker {len(names) + 1}")
        out.append({**segment, **({"speaker": names[who]} if who is not None else {})})
    return out


def assign_speakers(segments, turns):
    """Label timed segments with the speaker whose turns overlap them most. A segment that no turn touches takes the
    previous segment's speaker (the first one, the first speaker). Returns new segments, with a raw speaker id."""
    out, last = [], None
    for segment in segments:
        overlap = {}
        for turn in turns:
            span = min(segment["end"], turn["end"]) - max(segment["start"], turn["start"])
            if span > 0:
                overlap[turn["speaker"]] = overlap.get(turn["speaker"], 0) + span
        who = max(overlap, key=overlap.get) if overlap else (last if last is not None else (turns[0]["speaker"] if turns else None))
        last = who
        out.append({**segment, **({"speaker": who} if who is not None else {})})
    return out


def merge_same_speaker(segments, max_gap=2.0, max_len=45.0):
    """Join neighbouring segments of one speaker (a short gap apart) into one line, so a long answer reads as one."""
    out = []
    for segment in segments:
        before = out[-1] if out else None
        if (before and before.get("speaker") == segment.get("speaker") and before.get("start") is not None and segment.get("start") is not None
                and segment["start"] - before["end"] <= max_gap and segment["end"] - before["start"] <= max_len):
            out[-1] = {**before, "end": segment["end"], "text": f"{before['text']} {segment['text']}".strip()}
        else:
            out.append(dict(segment))
    return out


def render(segments, title="Transcript"):
    """{"transcript.md", "transcript.txt", plus transcript.srt and .vtt when every segment has times} for the segments."""
    timed = bool(segments) and all(segment.get("start") is not None for segment in segments)
    spoken = any(segment.get("speaker") for segment in segments)
    md, txt = [f"# {title}", ""], []
    if timed or spoken:
        for segment in segments:
            label = f"{f'[{mmss(segment['start'])}] ' if timed else ''}{f'{segment['speaker']}:' if segment.get('speaker') else ''}".strip()
            md += [f"**{label}** {segment['text']}", ""]
            txt.append(f"{label} {segment['text']}")
        files = {"transcript.md": "\n".join(md), "transcript.txt": "\n".join(txt) + "\n"}
    else:
        for paragraph in paragraphs(" ".join(segment["text"] for segment in segments)):
            md += [paragraph, ""]
            txt.append(paragraph)
        files = {"transcript.md": "\n".join(md), "transcript.txt": "\n\n".join(txt) + "\n"}
    if timed:
        cues = []
        for number, segment in enumerate(segments, 1):
            who = f"{segment['speaker']}: " if segment.get("speaker") else ""
            cues += [str(number), f"{srt_time(segment['start'])} --> {srt_time(max(segment['end'], segment['start'] + 0.5))}", f"{who}{segment['text']}", ""]
        files["transcript.srt"] = "\n".join(cues)
        files["transcript.vtt"] = "\n".join(["WEBVTT", ""] + [line.replace(",", ".") if " --> " in line else line for line in cues])
    return files
