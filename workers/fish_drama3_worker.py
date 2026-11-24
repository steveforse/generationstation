"""Fish Audio Drama 3 speech worker: a Windows worker in front of a Drama 3 server running inside WSL.

Two engines, chosen by the preset:
  sglang  SGLang-Omni with a single-card checkpoint (the NVFP4 build on the RTX 5090): fast, about 3x real time.
  fish    Fish Audio's own code with the full FP8-expert checkpoint over both cards: the most expressive, about
          0.6x real time, and it takes a seed.
Both need Linux (SGLang's kernels; Fish lists only Linux/WSL), so this worker starts the server in WSL and passes
jobs to it. It needs only Python's standard library.

The app stops workers by terminating them, which a WSL process does not notice. So the server runs under a small
watchdog in WSL that stops it when this worker's heartbeat file goes stale, and every start first stops a server
left over from an earlier start.

Scenes are spoken in one pass per block with Drama 3's speaker tags (<|speaker:N|>), as Fish Audio's own code does.
Local patches (workers/patches) are applied at start when a checkout lacks them:
  sglang-omni-drama3.patch        speaker tags other than 0 (upstream refuses them), and no crash on the empty
                                  logits of FlashInfer's MoE autotune pass
  fish-speech-drama3-two-cards.patch  the backbone split by weight (FISH_DRAMA3_DEVICE_WEIGHTS) and the codebook
                                  tower sharing the last card, so the full model fits a 32 GB + 16 GB pair; and
                                  CUDA graphs per card for that split (Fish only captured them on one card), which
                                  makes decoding about 3.8x faster with the same audio
SGLang samples with Fish's reference sampling at temperature 1.0, top-p 1.0, epsilon 1e-3 (at 0.7/0.7 its takes
fell silent); Fish's own server uses its defaults (0.7/0.7, top-k 30).

A take can fall silent part-way: it then runs to the frame limit, or ends early without some lines. Takes are
checked (frame limit, speech length, and with a small Whisper on the CPU the words heard) and made again, up to
RETRIES times. Long silences inside a take are shortened and trailing silence is trimmed.

Config options (from runtimes.json, per preset):
    engine          "sglang" (default) or "fish".
    distro          WSL distribution ("Ubuntu").
    server_dir      The engine's checkout with its .venv, as a WSL path ("~/ai/sglang-omni", "~/ai/fish-speech").
    model_path      The Drama 3 checkpoint, as a WSL path.
    server_port     The server's port (WSL forwards it to Windows' 127.0.0.1).
    wsl_gpus        CUDA indices of the cards inside WSL ("0", or "0,1" for the full model).
    max_frames      A take's frame limit (about 21.5 frames/s).
    serve_args      sglang: extra `sgl-omni serve` arguments (memory shares, reference sampling, MoE backend).
    device_weights  fish: the backbone's share per card ("0.81,0.19").
    check_python    Optional: python.exe of an environment with transformers and soundfile, for asr_check.py.
    check_model     Optional: a Whisper folder for the check (openai/whisper-base.en runs on the CPU).

Inputs: mode ("speak" | "scene"); speak: prompt, sample ([{"path"}], optional), sample_text; scene: script
("Name: line" per line), voices ([{"path"}], optional, in order of first appearance), voice_texts (one line each);
seed (optional; the fish engine follows it).
"""
import array
import base64
import io
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path, PureWindowsPath

from gs_worker import serve

HEARTBEAT_SECONDS = 3
STALE_SECONDS = 20          # the watchdog stops the server when the heartbeat is older than this
READY_SECONDS = 1200        # a first start compiles GPU code for the card (about 6 minutes); later ones about 3
GAP_SECONDS = 0.35          # silence between blocks
BLOCK_BYTES = 200           # text per request (UTF-8 bytes): Fish's own 300 assume a 1024-frame limit, this one is 512
BLOCK_SPEAKERS = 3          # at most three speakers per request, as Fish's own chunking
VOICE_BYTES = 120           # text of a voice take reused as a reference (references are limited to 15 s)
MAX_SPEAKERS = 8
RETRIES = 3
FRAMES_PER_SECOND = 44100 / 2048   # Drama 3's codec frame rate
SGLANG_SAMPLING = {"temperature": 1.0, "top_p": 1.0, "epsilon_cutoff": 0.001}  # Fish's reference-sampling settings
# A take is kept when it did not run to the frame limit, holds at least MIN_SPEECH of the speech its text needs
# (CHARS_PER_SECOND), and, with the speech-to-text check, at least MIN_RECALL of its words. Measured on 31 takes
# with known outcomes: every complete take had a speech ratio of 0.68 or more, six of ten failures less than 0.6.
MIN_SPEECH = 0.62
CHARS_PER_SECOND = 13.0
MIN_RECALL = 0.8
LONG_PAUSE = 1.2            # silences longer than this (seconds) are shortened to KEEP_PAUSE
KEEP_PAUSE = 0.7
LINE = re.compile(r"^\s*([^:\n]{1,40}):\s*(.+?)\s*$")
TAGS = re.compile(r"\[[^\[\]]*\]|<\|speaker:\d+\|>")
WORD = re.compile(r"[a-z0-9']+")
SENTENCE = re.compile(r"(?<=[.!?…。！？])\s+")
PATCHES = Path(__file__).resolve().parent / "patches"

WATCHDOG = r"""
server=$!
echo "$server" > "$PIDFILE"
stop() {{ kill -TERM -- "-$server" 2>/dev/null; for _ in $(seq 1 20); do kill -0 "$server" 2>/dev/null || break; sleep 1; done; kill -KILL -- "-$server" 2>/dev/null; rm -f "$PIDFILE"; }}
trap 'stop; exit 0' TERM INT HUP
while kill -0 "$server" 2>/dev/null; do
  age=$(( $(date +%s) - $(stat -c %Y {heartbeat} 2>/dev/null || echo 0) ))
  if [ "$age" -gt {stale} ]; then echo "[drama3] the worker's heartbeat stopped ${{age}} s ago: stopping the server"; stop; exit 0; fi
  sleep 3
done
rm -f "$PIDFILE"
wait "$server"; exit $?
"""
PREAMBLE = r"""#!/usr/bin/env bash
# Runs Drama 3 and stops it when the Windows worker's heartbeat goes stale.
set -u
PIDFILE="$HOME/.gs-drama3.pid"
if [ -f "$PIDFILE" ]; then  # a server left from an earlier start
  old=$(cat "$PIDFILE"); kill -TERM -- "-$old" 2>/dev/null; sleep 5; kill -KILL -- "-$old" 2>/dev/null; rm -f "$PIDFILE"
fi
if [ ! -d {model} ]; then
  echo "[drama3] The model folder {model} is not visible in WSL. If it is on D:, mount D: in WSL (sudo mount -t drvfs D: /mnt/d) or add it to /etc/fstab." >&2
  exit 3
fi
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES={gpus}
cd {server_dir} || exit 4
if {needs_patch}; then
  # An older version of the patch may be applied: start the files it touches from the checkout's own versions.
  git checkout -- $(git apply --numstat {patch} | cut -f3)
  git apply {patch} && echo "[drama3] applied {patch_name}" || {{ echo "[drama3] {patch_name} does not apply to this checkout" >&2; exit 5; }}
fi
# The environment's tools (ninja builds kernels during start-up) must be on PATH, as after `activate`.
export VIRTUAL_ENV="$PWD/.venv" PATH="$PWD/.venv/bin:$PATH"
"""
SGLANG_START = r"""setsid .venv/bin/sgl-omni serve --model-path {model} --host 127.0.0.1 --port {port} --tts_engine.factory.max_new_tokens {max_frames} {serve_args} &"""
FISH_START = r"""export FISH_DRAMA3_DEVICE_WEIGHTS={weights} FISH_DRAMA3_FP8_EXPERTS=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
setsid .venv/bin/python tools/api_server.py --listen 127.0.0.1:{port} --llama-checkpoint-path {model} --device {devices} &"""
ENGINES = {
    "sglang": {"dir": "~/ai/sglang-omni", "patch": "sglang-omni-drama3.patch", "start": SGLANG_START,
               # applied when the file still has upstream's refusal
               "needs_patch": "grep -q 'only speaker 0 is supported' sglang_omni/models/fishaudio_drama3/speech_request.py",
               "health": "/health"},
    "fish": {"dir": "~/ai/fish-speech", "patch": "fish-speech-drama3-two-cards.patch", "start": FISH_START,
             # applied when the decoder lacks the split-card CUDA graphs (the patch's latest part)
             "needs_patch": "! grep -q Drama3SplitDecodeGraphs fish_speech/models/text2semantic/fish_omni/generate.py",
             "health": "/v1/health"},
}


def wsl_path(path):
    """D:\\ai\\x.wav -> /mnt/d/ai/x.wav (WSL's view of a Windows path)."""
    windows = PureWindowsPath(path)
    if not windows.drive:
        return str(path).replace("\\", "/")
    return f"/mnt/{windows.drive[0].lower()}/" + "/".join(windows.parts[1:])


def _quote(text):
    return "'" + str(text).replace("'", "'\\''") + "'"


def parse_script(script):
    """Scene lines as (speaker, text), with lines that do not start with "Name:" joined to the line above."""
    lines = []
    for raw in (script or "").splitlines():
        if not raw.strip():
            continue
        match = LINE.match(raw)
        if match:
            lines.append((match.group(1).strip(), match.group(2)))
        elif lines:
            lines[-1] = (lines[-1][0], f"{lines[-1][1]} {raw.strip()}")
        else:
            raise ValueError('Each line of the scene starts with a name and a colon, such as "Anna: Hello."')
    if not lines:
        raise ValueError("The scene has no lines.")
    return lines


def spoken(text):
    """A text's words without its [tags] and speaker tags."""
    return re.sub(r"\s+", " ", TAGS.sub(" ", text)).strip()


def split_long(text, limit=BLOCK_BYTES):
    """Text in pieces of at most `limit` UTF-8 bytes, cut at sentence ends where possible (else at spaces)."""
    pieces = []
    for sentence in SENTENCE.split(text.strip()):
        while len(sentence.encode()) > limit:
            cut = sentence.encode()[:limit].decode(errors="ignore").rfind(" ")
            cut = cut if cut > 0 else len(sentence.encode()[:limit].decode(errors="ignore"))
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    blocks, current = [], ""
    for piece in pieces:
        joined = f"{current} {piece}".strip()
        if current and len(joined.encode()) > limit:
            blocks.append(current)
            current = piece
        else:
            current = joined
    if current:
        blocks.append(current)
    return blocks


def voice_text(text, limit=VOICE_BYTES):
    """The opening of a text for a short voice take: its first sentences up to `limit` bytes (at least one,
    cut at a space when that alone is longer)."""
    return split_long(text, limit)[0]


def scene_blocks(lines, limit=BLOCK_BYTES, speakers=BLOCK_SPEAKERS):
    """Consecutive (speaker id, text) turns grouped into blocks of at most `limit` bytes and `speakers` voices.
    A turn longer than the limit is split into several turns of the same speaker."""
    turns = [(who, piece) for who, text in lines for piece in split_long(text, limit)]
    blocks, current = [], []
    for who, text in turns:
        candidate = [*current, (who, text)]
        size = sum(len(f"<|speaker:{w}|>{t} ".encode()) for w, t in candidate)
        if current and (size > limit or len({w for w, _ in candidate}) > speakers):
            blocks.append(current)
            current = [(who, text)]
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def tagged(block):
    return " ".join(f"<|speaker:{who}|>{text}" for who, text in block)


# ----- audio ---------------------------------------------------------------------------------------

def _read(data):
    with wave.open(io.BytesIO(data)) as clip:
        return clip.getparams(), clip.readframes(clip.getnframes())


def _write(params, frames):
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(params.nchannels)
        clip.setsampwidth(params.sampwidth)
        clip.setframerate(params.framerate)
        clip.writeframes(frames)
    return out.getvalue()


def tidy_pauses(data, long_pause=LONG_PAUSE, keep=KEEP_PAUSE, tail=0.3):
    """The take with silences longer than `long_pause` s shortened to `keep` s and trailing silence cut to `tail` s.
    16-bit PCM only; other formats are returned unchanged."""
    params, frames = _read(data)
    if params.sampwidth != 2:
        return data
    samples = array.array("h", frames)
    window = int(params.framerate * 0.02) * params.nchannels
    out = array.array("h")
    run = []
    for start in range(0, len(samples), window):
        piece = samples[start:start + window]
        if piece and max(abs(s) for s in piece) > 600:
            if len(run) * 0.02 > long_pause:
                run = run[:int(keep / 0.02)]
            for quiet in run:
                out.extend(quiet)
            run = []
            out.extend(piece)
        else:
            run.append(piece)
    for quiet in run[:int(tail / 0.02)]:
        out.extend(quiet)
    return _write(params, out.tobytes())


def speech_seconds(data):
    """Seconds of a take that are not silence (20 ms windows with a peak above a quiet threshold)."""
    params, frames = _read(data)
    if params.sampwidth != 2:
        return wav_seconds(data)
    samples = array.array("h", frames)
    window = int(params.framerate * 0.02) * params.nchannels
    return sum(0.02 for start in range(0, len(samples), window)
               if max((abs(s) for s in samples[start:start + window]), default=0) > 600)


def needed_seconds(text):
    """About how long the words of a text take to say (letters without spaces, at CHARS_PER_SECOND)."""
    return max(len(spoken(text).replace(" ", "")) / CHARS_PER_SECOND, 0.5)


def recall(expected, heard):
    """The share of the expected words found in what was heard (each heard word counts once)."""
    want = WORD.findall(expected.lower().replace("\u2019", "'"))
    pool = {}
    for word in WORD.findall(heard.lower().replace("\u2019", "'")):
        pool[word] = pool.get(word, 0) + 1
    found = 0
    for word in want:
        if pool.get(word):
            pool[word] -= 1
            found += 1
    return found / len(want) if want else 1.0


def join_wavs(parts, gap=GAP_SECONDS):
    """WAV files (bytes) joined with a short silence, as one WAV (bytes)."""
    params, frames = None, []
    for data in parts:
        current, body = _read(data)
        if params is None:
            params = current
        elif (current.nchannels, current.sampwidth, current.framerate) != (params.nchannels, params.sampwidth, params.framerate):
            raise ValueError("The takes came back in different audio formats.")
        frames.append(body)
    silence = b"\0" * int(params.framerate * gap) * params.nchannels * params.sampwidth
    return _write(params, silence.join(frames))


def wav_seconds(data):
    with wave.open(io.BytesIO(data)) as clip:
        return clip.getnframes() / clip.getframerate()


# ----- the speech-to-text check --------------------------------------------------------------------

class Checker:
    """workers/asr_check.py in another environment, kept running: what a take actually says."""

    def __init__(self, python, model, folder, log):
        self.folder, self.log = Path(folder), log
        script = Path(__file__).resolve().parent / "asr_check.py"
        self.process = subprocess.Popen([python, str(script), model], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.lock = threading.Lock()
        if json.loads(self.process.stdout.readline() or "{}").get("ready") is not True:
            raise RuntimeError("The speech-to-text check did not start.")

    def heard(self, data):
        path = self.folder / "check-take.wav"
        with self.lock:
            path.write_bytes(data)
            self.process.stdin.write(json.dumps({"path": str(path)}) + "\n")
            self.process.stdin.flush()
            answer = json.loads(self.process.stdout.readline() or "{}")
        if "text" not in answer:
            raise RuntimeError(answer.get("error") or "The speech-to-text check stopped.")
        return answer["text"]


# ----- the server ----------------------------------------------------------------------------------

def voice(path, transcript, speaker=0):
    """A reference voice: a WAV on the Windows side, what it says, and the speaker it voices."""
    return {"path": str(path), "text": (transcript or "").strip(), "speaker": speaker}


class Server:
    def __init__(self, options, launch_dir, log):
        self.options, self.log = options, log
        self.engine = options.get("engine", "sglang")
        if self.engine not in ENGINES:
            raise ValueError(f"Unknown Drama 3 engine {self.engine!r}.")
        self.port = int(options.get("server_port", 8251))
        self.max_frames = int(options.get("max_frames", 512))
        self.heartbeat = Path(launch_dir) / "drama3-heartbeat"
        self.wrapper = Path(launch_dir) / "drama3-serve.sh"
        self.process = None
        self.checker = None
        self.stopping = threading.Event()

    def _beat(self):
        while not self.stopping.is_set():
            self.heartbeat.touch()
            time.sleep(HEARTBEAT_SECONDS)

    def script(self):
        options, engine = self.options, ENGINES[self.engine]
        gpus = str(options.get("wsl_gpus", options.get("wsl_gpu", "0")))
        cards = [g for g in gpus.split(",") if g.strip()]
        model = _quote(options["model_path"])
        preamble = PREAMBLE.format(model=model, gpus=gpus, needs_patch=engine["needs_patch"],
                                   server_dir=options.get("server_dir", options.get("sglang_dir", engine["dir"])),
                                   patch=_quote(wsl_path(PATCHES / engine["patch"])), patch_name=engine["patch"])
        devices = ",".join(f"cuda:{i}" for i in range(len(cards)))
        if len(cards) > 1:
            devices += f",cuda:{len(cards) - 1}"  # the codebook tower shares the last card
        start = engine["start"].format(model=model, port=self.port, max_frames=self.max_frames,
                                       serve_args=options.get("serve_args", ""),
                                       weights=_quote(options.get("device_weights", "")), devices=devices)
        return preamble + start + WATCHDOG.format(heartbeat=_quote(wsl_path(self.heartbeat)), stale=STALE_SECONDS)

    def start(self):
        self.heartbeat.touch()
        threading.Thread(target=self._beat, daemon=True, name="drama3-heartbeat").start()
        self.wrapper.write_bytes(self.script().replace("\r\n", "\n").encode())
        argv = ["wsl.exe", "-d", self.options.get("distro", "Ubuntu"), "--", "bash", wsl_path(self.wrapper)]
        self.log(f"starting Drama 3 ({self.engine}) in WSL on port {self.port}")
        # Its output goes to this worker's log, so the Logs page shows the server's own messages.
        self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL)
        started = time.monotonic()
        while time.monotonic() - started < READY_SECONDS:
            if self.process.poll() is not None:
                raise RuntimeError(f"The Drama 3 server stopped while starting (exit {self.process.returncode}); "
                                   "its messages are in this log.")
            if self.ready():
                self.log(f"Drama 3 ready in {time.monotonic() - started:.0f} s")
                return
            time.sleep(3)
        raise RuntimeError(f"The Drama 3 server was not ready within {READY_SECONDS // 60} minutes.")

    def ready(self):
        try:
            url = f"http://127.0.0.1:{self.port}{ENGINES[self.engine]['health']}"
            with urllib.request.urlopen(url, timeout=4) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def body(self, text, voices, seed=None):
        """The request for this engine: SGLang reads reference files from WSL paths; Fish's server takes them
        inline (base64) with their speaker numbers, and follows a seed."""
        if self.engine == "fish":
            body = {"text": text, "format": "wav", "normalize": False, "max_new_tokens": self.max_frames,
                    "references": [{"audio": base64.b64encode(Path(v["path"]).read_bytes()).decode(), "text": v["text"],
                                    "speaker": v["speaker"]} for v in voices]}
            if isinstance(seed, int):
                body["seed"] = seed
            return f"http://127.0.0.1:{self.port}/v1/tts", body
        body = {"input": text, "stream": False, **SGLANG_SAMPLING}
        if voices:
            body["references"] = [{"audio_path": wsl_path(v["path"]), "text": f"<|speaker:{v['speaker']}|> {v['text']}".rstrip()}
                                  for v in voices]
        return f"http://127.0.0.1:{self.port}/v1/audio/speech", body

    def request(self, text, voices=(), seed=None):
        url, body = self.body(text, list(voices), seed)
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                detail = (parsed.get("error") or {}).get("message") if isinstance(parsed.get("error"), dict) else parsed.get("message", detail)
            except (ValueError, AttributeError):
                pass
            raise RuntimeError(f"Drama 3 refused the request: {detail}") from None

    def speak(self, text, voices=(), job=None, label="", seed=None):
        """One take that says its whole text: made again (up to RETRIES times) when it ran to the frame limit, is
        too short for its words, or (with the speech-to-text check) left words out. Otherwise the best one is kept."""
        limit = self.max_frames / FRAMES_PER_SECOND - 0.6
        expected = spoken(text)
        best = None
        for attempt in range(1, RETRIES + 1):
            raw = self.request(text, voices, None if seed is None else seed + attempt - 1)
            capped = wav_seconds(raw) >= limit
            data = tidy_pauses(raw)
            ratio = speech_seconds(data) / needed_seconds(text)
            share = None
            if self.checker is not None and not capped:
                try:
                    share = recall(expected, self.checker.heard(data))
                except (OSError, RuntimeError, ValueError) as exc:
                    self.log(f"the speech-to-text check failed ({exc}); going on without it")
                    self.checker = None
            problem = ("it ran to the frame limit" if capped else f"it has too little speech ({ratio:.2f})"
                       if ratio < MIN_SPEECH else f"it left words out ({share:.2f} of them heard)"
                       if share is not None and share < MIN_RECALL else None)
            if problem is None:
                return data, attempt
            score = (not capped, share if share is not None else ratio, ratio)
            if best is None or score > best[0]:
                best = (score, data)
            self.log(f"{label or 'take'}: {problem} (attempt {attempt})")
            if job is not None and attempt < RETRIES:
                job.report(f"{label or 'Speaking'}: the take was incomplete, trying again ({attempt + 1} of {RETRIES})")
        return best[1], RETRIES


def load(config, log=print):
    launch_dir = Path(config.get("launch_dir") or Path(config.get("config_path", ".")).parent)
    options = config["options"]
    server = Server(options, launch_dir, lambda message: log(f"[worker] {message}"))
    if options.get("check_python") and options.get("check_model"):
        try:
            server.checker = Checker(options["check_python"], options["check_model"], launch_dir, server.log)
            server.log("speech-to-text check ready")
        except (OSError, RuntimeError, ValueError) as exc:
            server.log(f"the speech-to-text check could not start ({exc}); takes are checked by length only")
    server.start()
    return {"server": server}


def _voice_take(server, job, text, name, number, seed):
    """A short take of `text` in a voice the model picks, saved in the job's folder as a reference (not a result)."""
    line = voice_text(text)
    job.report(f"Finding a voice for {name}")
    data, attempts = server.speak(f"<|speaker:0|>{line}", (), job, f"Voice for {name}", seed)
    path = Path(job.dir) / "voices" / f"voice-{number}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, spoken(line), attempts - 1


def _seed(inputs):
    seed = inputs.get("seed")
    return seed if isinstance(seed, int) else None


def _speak(server, inputs, job):
    text = (inputs.get("prompt") or "").strip()
    sample = (inputs.get("sample") or [None])[0]
    seed = _seed(inputs)
    voices = [voice(sample["path"], inputs.get("sample_text"))] if sample else []
    blocks = split_long(text)
    retried = 0
    if not voices and len(blocks) > 1:
        # Without a sample the model picks a voice, a different one per request: a short take of the opening
        # becomes the voice of every part.
        path, said, retried = _voice_take(server, job, text, "the reading", 1, seed)
        voices = [voice(path, said)]
    takes = []
    for number, block in enumerate(blocks, 1):
        job.report(f"Speaking part {number} of {len(blocks)}" if len(blocks) > 1 else "Speaking")
        data, attempts = server.speak(block, voices, job, f"Part {number}", None if seed is None else seed + 100 * number)
        retried += attempts - 1
        takes.append(data)
    job.detail(mode="speak", voice="cloned from the sample" if sample else "chosen by the model", parts=len(blocks),
               retried=retried, engine=server.engine, seed=seed)
    return join_wavs(takes), "speech.wav"


def _scene(server, inputs, job):
    lines = parse_script(inputs.get("script"))
    names = list(dict.fromkeys(name for name, _ in lines))
    if len(names) > MAX_SPEAKERS:
        raise ValueError(f"Use at most {MAX_SPEAKERS} characters in one scene.")
    ids = {name: number for number, name in enumerate(names)}
    samples = inputs.get("voices") or []
    texts = (inputs.get("voice_texts") or "").splitlines()
    seed = _seed(inputs)
    voices = {ids[name]: voice(samples[i]["path"], texts[i] if i < len(texts) else "", ids[name])
              for i, name in enumerate(names) if i < len(samples)}
    blocks = scene_blocks([(ids[name], text) for name, text in lines])
    retried = 0
    if len(blocks) > 1:
        # Several blocks: every character needs a reference so they sound the same in each one. A character
        # without a sample gets a short take of their first line in a voice the model picks.
        for name in names:
            who = ids[name]
            if who in voices:
                continue
            first = next(text for n, text in lines if n == name)
            path, said, extra = _voice_take(server, job, first, name, who + 1, None if seed is None else seed + who)
            retried += extra
            voices[who] = voice(path, said, who)
    takes = []
    for number, block in enumerate(blocks, 1):
        job.report(f"Performing part {number} of {len(blocks)}" if len(blocks) > 1 else "Performing the scene")
        present = sorted({who for who, _ in block})
        data, attempts = server.speak(tagged(block), [voices[who] for who in present if who in voices], job,
                                      f"Part {number}", None if seed is None else seed + 100 * number)
        retried += attempts - 1
        takes.append(data)
    job.detail(mode="scene", lines=len(lines), speakers=names, parts=len(blocks), retried=retried, engine=server.engine,
               seed=seed, cloned=[name for i, name in enumerate(names) if i < len(samples)])
    return join_wavs(takes), "scene.wav"


def generate(state, inputs, job):
    server = state["server"]
    started = time.perf_counter()
    if (inputs.get("mode") or "speak") == "scene":
        data, name = _scene(server, inputs, job)
    else:
        data, name = _speak(server, inputs, job)
    path = job.output(name, "audio/wav")
    path.write_bytes(data)
    seconds = wav_seconds(data)
    job.detail(audio_seconds=round(seconds, 1))
    job.report(f"Done: {seconds:.0f} seconds of speech in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    serve(load, generate)
