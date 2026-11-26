"""Reads a transcript someone already has (Zoom's .vtt or .txt, an .srt, a notes file) into the worker's segments.

A segment is {"speaker": str, "start": float | None, "end": float | None, "text": str}. Names written in the file
are kept as the speaker labels. Times are seconds from the first stamp; a transcript with none has `start` and `end`
of None and is "untimed" (the worker then writes no captions and no [mm:ss] markers).
"""
import re

MAX_WORDS = 30000  # about three hours of talk: the notes read the whole transcript in one request
GROUP_WORDS = 80  # an unattributed stream of cues is cut into turns of about this many words
STAMP = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
CUE = re.compile(rf"^\s*({STAMP})\s*-->\s*({STAMP})")
ZOOM_HEADER = re.compile(rf"^\s*\[(.+?)\]\s+({STAMP})\s*$")
LEADING_STAMP = re.compile(rf"^\s*[\[(]?({STAMP})[\])]?\s*[-–—:]?\s*")
SPEAKER_LINE = re.compile(r"^\s*([^\W\d_][^:\n.!?,;]{0,39}?):\s+(\S.*)$")  # a name, not the end of a sentence
VOICE = re.compile(r"<v(?:\.\w+)*\s+([^>]+)>")
TAGS = re.compile(r"</?[^>]+>")


class TranscriptError(ValueError):
    pass


def seconds(stamp):
    parts = stamp.replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def clean(text):
    return " ".join(TAGS.sub("", text).split())


def merge(segments):
    """Consecutive pieces by the same speaker become one turn."""
    turns = []
    for piece in segments:
        if turns and turns[-1]["speaker"] == piece["speaker"] and piece["speaker"] is not None:
            turns[-1]["text"] += " " + piece["text"]
            turns[-1]["end"] = piece["end"] if piece["end"] is not None else turns[-1]["end"]
        else:
            turns.append(dict(piece))
    return turns


def cues(lines):
    """WebVTT or SRT: blocks with a timing line, then the words (optionally "Name: words" or <v Name>words)."""
    pieces, block = [], []
    for line in lines + [""]:
        if line.strip():
            block.append(line)
            continue
        if block:
            at = next((i for i, text in enumerate(block) if CUE.match(text)), None)
            if at is not None:
                match = CUE.match(block[at])
                body = " ".join(text.strip() for text in block[at + 1:])
                speaker = None
                voice = VOICE.search(body)
                if voice:
                    speaker = voice.group(1).strip()
                words = clean(body)
                if not voice:
                    named = SPEAKER_LINE.match(words)
                    if named:
                        speaker, words = named.group(1).strip(), named.group(2).strip()
                if words:
                    pieces.append({"speaker": speaker, "start": seconds(match.group(1)), "end": seconds(match.group(2)), "text": words})
            block = []
    return pieces


def zoom_text(lines):
    """Zoom's audio transcript .txt: "[Name] 00:01:02" on one line, the words on the next."""
    pieces, who, when, said = [], None, None, []

    def flush():
        if who is not None and said:
            pieces.append({"speaker": who, "start": when, "end": when, "text": clean(" ".join(said))})

    for line in lines:
        header = ZOOM_HEADER.match(line)
        if header:
            flush()
            who, when, said = header.group(1).strip(), seconds(header.group(2)), []
        elif line.strip():
            said.append(line.strip())
    flush()
    return pieces


def dialogue(lines):
    """"Name: words" lines, optionally led by a time; a line that is not one continues the line before."""
    pieces = []
    for line in lines:
        if not line.strip():
            continue
        stamp = LEADING_STAMP.match(line)
        body = line[stamp.end():] if stamp else line
        named = SPEAKER_LINE.match(body)
        if named:
            pieces.append({"speaker": named.group(1).strip(), "start": seconds(stamp.group(1)) if stamp else None,
                           "end": None, "text": clean(named.group(2))})
        elif pieces:
            pieces[-1]["text"] += " " + clean(body)
        else:
            pieces.append({"speaker": None, "start": None, "end": None, "text": clean(body)})
    return pieces


def paragraphs(text):
    """No speakers and no times: each paragraph is a turn by one unnamed speaker."""
    return [{"speaker": None, "start": None, "end": None, "text": clean(block)} for block in re.split(r"\n\s*\n", text) if block.strip()]


def group(pieces):
    """Cut a long run of unattributed cues into turns, so correction and notes see sensible chunks."""
    out, words = [], 0
    for piece in pieces:
        if out and words < GROUP_WORDS:
            out[-1]["text"] += " " + piece["text"]
            out[-1]["end"] = piece["end"]
            words += len(piece["text"].split())
        else:
            out.append(dict(piece))
            words = len(piece["text"].split())
    return out


def parse(text):
    """The transcript's segments and whether it has times."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    if not text.strip():
        raise TranscriptError("That transcript is empty.")
    if text.lstrip().startswith("WEBVTT") or any(CUE.match(line) for line in lines):
        pieces = cues(lines)
    elif sum(1 for line in lines if ZOOM_HEADER.match(line)) >= 2:
        pieces = zoom_text(lines)
    else:
        spoken = [line for line in lines if line.strip()]
        named = sum(1 for line in spoken if SPEAKER_LINE.match(LEADING_STAMP.sub("", line, count=1)))
        pieces = dialogue(lines) if spoken and named * 2 >= len(spoken) else paragraphs(text)
    if not pieces:
        raise TranscriptError("No speech was found in that transcript.")
    if any(piece["speaker"] is None for piece in pieces) and all(piece["speaker"] is None for piece in pieces):
        pieces = group(pieces) if any(piece["start"] is not None for piece in pieces) else pieces
    turns = merge(pieces)
    timed = any(turn["start"] is not None for turn in turns)
    if timed:
        first = min(turn["start"] for turn in turns if turn["start"] is not None)
        last = 0.0
        for turn in turns:
            turn["start"] = (turn["start"] if turn["start"] is not None else last) - first
            turn["end"] = (turn["end"] if turn["end"] is not None else turn["start"] + first) - first
            turn["end"] = max(turn["end"], turn["start"])
            last = turn["end"] + first
    if sum(len(turn["text"].split()) for turn in turns) > MAX_WORDS:
        raise TranscriptError(f"That transcript is too long (over {MAX_WORDS:,} words).")
    for turn in turns:
        turn["speaker"] = turn["speaker"] or "Speaker 1"
    return turns, timed


# ----- writing a transcript out (shared by the worker and the host's transcript editor) ------------------------------

def mmss(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60:02d}:{seconds % 60:02d}"


def srt_time(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def render(segs, names):
    """{"transcript.md": text, "transcript.srt": text, "transcript.vtt": text} for segments {speaker, start, end, text};
    `names` maps a speaker label to the name the notes proposed for it. A transcript without times has no captions."""
    who = lambda label: f"{label} ({names[label]})" if names.get(label) else label
    lines = ["# Transcript", ""]
    for s in segs:
        stamp = f"[{mmss(s['start'])}] " if s.get("start") is not None else ""
        lines += [f"**{stamp}{who(s['speaker'])}:** {s['text']}", ""]
    files = {"transcript.md": "\n".join(lines)}
    if all(s.get("start") is not None for s in segs):
        srt = []
        for n, s in enumerate(segs, 1):
            srt += [str(n), f"{srt_time(s['start'])} --> {srt_time(max(s['end'], s['start'] + 0.5))}", f"{who(s['speaker'])}: {s['text']}", ""]
        files["transcript.srt"] = "\n".join(srt)
        # The same cues for web players and Zoom's own caption import: a header and dots instead of commas in the times.
        files["transcript.vtt"] = "\n".join(["WEBVTT", ""] + [line.replace(",", ".") if " --> " in line else line for line in srt])
    return files
