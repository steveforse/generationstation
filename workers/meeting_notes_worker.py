"""Meeting notes: a recording in, a speaker-labelled transcript, a summary, action items and decisions out.

Each job: convert the recording to 16 kHz mono (ffmpeg in WSL); wait until the card has room; run the speech engine
in WSL (workers/meeting_pipeline.py, one process per step that exits when done, so the card is free afterwards);
then, for notes, ask the host for a text model (job.need("text_model")): the host starts one if none runs, through
its normal capacity checks, and may stop it again when the job ends. With it the worker corrects the transcript in
chunks and extracts the notes as checked JSON.

Engines (options.engine), from the 2026-11-23 bake-off on four AMI meetings (speaker-attributed word error):
  nemotron   NVIDIA Nemotron 3.5 Transcribe (NVFP4, vLLM on a Unix socket), 17.3%; RTX 5090 only (Blackwell);
             its server starts per job (about 3.5 minutes once the kernels are compiled) and stops after.
  qwen       DiariZen speaker turns, then Qwen3-ASR-1.7B per turn, 24.3%; about 11 GiB, either card, under a minute
             for a 25-minute meeting.
  vibevoice  VibeVoice-ASR (one pass), 35.1%; about 19 GiB.
  mlx        Apple silicon, no WSL (options.distro "local"): sherpa-onnx speaker turns on the processor, then
             Qwen3-ASR on MLX per turn. Steps run as plain child processes of this worker.

The app stops a worker by terminating it, which does not reach processes inside WSL, so every WSL step runs under a
watchdog that ends it when the worker's heartbeat file goes stale.
"""
import contextlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path, PureWindowsPath

import meeting_transcript
from gs_worker import JobCancelled, serve

HEARTBEAT_SECONDS = 5
STALE_SECONDS = 30
CHUNK_WORDS = 1200
WATCHDOG = r"""HB="$1"; shift
setsid "$@" &
CP=$!
while kill -0 $CP 2>/dev/null; do
  age=$(( $(date +%s) - $(stat -c %Y "$HB" 2>/dev/null || echo 0) ))
  if [ $age -gt {stale} ]; then
    echo '{{"ok": false, "error": "the worker stopped; step ended"}}'
    kill -TERM -- -$CP 2>/dev/null || kill -TERM $CP; sleep 5; kill -KILL -- -$CP 2>/dev/null
    exit 3
  fi
  sleep 2
done
wait $CP
""".replace("{stale}", str(STALE_SECONDS))
NEMOTRON_SERVE = r"""source {venv}/bin/activate
export PATH=/usr/local/cuda/bin:$PATH VLLM_PLUGINS=nemo_speechlm VLLM_MAX_AUDIO_DECODE_DURATION_S=3600
export VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=180 VLLM_USE_V2_MODEL_RUNNER=0 VLLM_DISABLED_KERNELS=FlashInferFP8ScaledMMLinearKernel
# FlashInfer compiles its kernels on first use, one compiler per core; 32 at once ran WSL out of memory.
export MAX_JOBS=6
rm -f {socket}
# A Unix socket: TCP connections to vLLM's port were dropped in this WSL (2026-11-23).
exec vllm serve {model} --served-model-name nemotron --uds {socket} \
  --trust-remote-code --dtype bfloat16 --kv-cache-dtype fp8 --gpu-memory-utilization {util} \
  --max-model-len 65536 --max-num-batched-tokens 4096 --max-num-seqs 2 \
  --enable-chunked-prefill --no-enable-prefix-caching \
  --use-replayssm --mamba-backend flashinfer --mamba-cache-mode none \
  --mm-processor-cache-gb 0 --no-async-scheduling \
  --limit-mm-per-prompt '{{"audio":{{"count":1,"length":57600000}}}}' \
  --speculative-config '{{"method":"mtp","num_speculative_tokens":8}}' \
  --reasoning-parser nemotron_v3 --trust-request-mm-kwargs \
  --middleware nemo.collections.speechlm2.vllm.salm.ctc_serving.ctc_timestamp_middleware
"""

CORRECT = """You are correcting an automatic transcript of a meeting. Each line is one speaker turn: its number, then the text.
Fix only recognition errors: misheard words, wrong homophones, broken names and terms, obvious missing punctuation. Keep the
speaker's wording, fillers and false starts otherwise; do not summarise, merge, split, reorder or add turns, and never invent
content.
{terms}Answer with JSON only: {{"turns": [{{"n": <number>, "text": "<corrected text>"}}, ...]}} with one entry per turn, in order.

{lines}"""
EXTRACT = """Below is the transcript of a meeting. Each line: [mm:ss] speaker: text.
{people}
Write meeting notes as JSON only, in this shape:
{{"speakers": {{"<speaker label>": "<name or role, as the conversation shows it, or null>"}},
  "summary": ["<bullet>", ...],
  "actions": [{{"task": "<what will be done>", "owner": "<name or speaker, or null>", "due": "<when, or null>", "time": "<mm:ss where it was said>"}}],
  "decisions": [{{"decision": "<what was decided>", "by": "<who decided or agreed, or null>", "time": "<mm:ss>"}}]}}

Rules: the summary has 4-10 short bullets covering the main topics and outcomes. Actions are concrete follow-ups someone will
do after the meeting. Decisions are things the group settled or agreed on. Use only what the transcript says; give an empty
list when there are none. Times must point at the line that supports the item. Name a speaker only when the conversation
makes it clear (someone is addressed or introduces themselves); otherwise null.

Transcript:
{transcript}"""


def wsl_path(path):
    windows = PureWindowsPath(path)
    if not windows.drive:
        return str(path).replace("\\", "/")
    return f"/mnt/{windows.drive[0].lower()}/" + "/".join(windows.parts[1:])


mmss, srt_time = meeting_transcript.mmss, meeting_transcript.srt_time


class Heartbeat:
    """Touches a file every few seconds while a WSL step runs; the step's watchdog ends it when the touches stop."""

    def __init__(self, path):
        self.path, self.stop = Path(path), threading.Event()

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()
        threading.Thread(target=self._beat, daemon=True).start()
        return self

    def _beat(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            self.path.touch()

    def __exit__(self, *exc):
        self.stop.set()


class Worker:
    def __init__(self, config, log=print):
        self.options = config.get("options") or {}
        self.gpus = config.get("gpus") or [0]
        self.launch_dir = Path(config.get("launch_dir") or ".")
        self.log = log
        self.distro = self.options.get("distro", "Ubuntu")
        # "local": run the steps as child processes of this worker (macOS, Linux) instead of inside WSL.
        self.local = str(self.distro).lower() in ("", "local")
        self.watchdog = self.launch_dir / "meeting-watchdog.sh"
        self.heartbeat = self.launch_dir / "meeting-heartbeat"
        if not self.local:
            self.watchdog.write_text(WATCHDOG, encoding="utf-8", newline="\n")

    # ----- WSL steps ------------------------------------------------------------------------------

    def wsl(self, command, job=None, timeout=7200):
        """Run a shell command (in WSL under the heartbeat watchdog, or locally) and return the last JSON line it printed."""
        if self.local:
            env = dict(os.environ, TOKENIZERS_PARALLELISM="false", PYTHONUNBUFFERED="1")
            env["PATH"] = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "")])
            argv, kwargs = ["bash", "-c", command], {"env": env, "start_new_session": True}
        else:
            env = f"export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES={self.gpus[0]} TOKENIZERS_PARALLELISM=false;"
            argv = ["wsl.exe", "-d", self.distro, "--", "bash", wsl_path(self.watchdog), wsl_path(self.heartbeat),
                    "bash", "-lc", env + command]
            kwargs = {}
        with Heartbeat(self.heartbeat) if not self.local else contextlib.nullcontext():
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding="utf-8", errors="replace", **kwargs)
            lines, started = [], time.time()
            reader = threading.Thread(target=lambda: lines.extend(process.stdout), daemon=True)
            reader.start()
            while process.poll() is None:
                if job is not None and job.cancel_requested:
                    self.stop_heartbeat_and_wait(process)
                    raise JobCancelled()
                if time.time() - started > timeout:
                    self.stop_heartbeat_and_wait(process)
                    raise TimeoutError(f"a speech step took longer than {timeout} s")
                time.sleep(1)
            reader.join(5)
        result = None
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{") and '"ok"' in line:
                try:
                    result = json.loads(line)
                    break
                except ValueError:
                    pass
        if not result or not result.get("ok"):
            tail = "".join(lines[-15:]).strip()
            self.log(f"Speech step failed:\n{tail}")
            raise RuntimeError((result or {}).get("error") or f"a speech step failed: {tail[-500:]}")
        return result

    def stop_heartbeat_and_wait(self, process):
        """End the step: stop beating so the watchdog ends the WSL side, or signal the local step's process group."""
        if self.local:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return
        process.terminate()

    def card_free_gib(self):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=20, check=False).stdout
            free = {int(i): int(m) for i, m in (line.split(",") for line in out.strip().splitlines())}
            return free.get(self.gpus[0], 0) / 1024
        except Exception:  # noqa: BLE001 - unknown: let the step try
            return None

    def wait_for_card(self, job, need_gib, limit=900):
        if self.local:
            return  # no separate card memory to wait for (Apple silicon shares memory; admission counts it as RAM)
        started = time.time()
        while True:
            free = self.card_free_gib()
            if free is None or free >= need_gib:
                return
            if time.time() - started > limit:
                raise RuntimeError(f"The card did not have {need_gib:.0f} GiB free within {limit // 60} minutes "
                                   f"({free:.1f} GiB free). Stop what is using it and try again.")
            job.report(f"Waiting for {need_gib:.0f} GiB on the card ({free:.1f} GiB free)")
            time.sleep(10)

    # ----- speech engines ---------------------------------------------------------------------------

    def transcribe(self, audio, work, terms, job):
        o = self.options
        script = wsl_path(Path(__file__).with_name("meeting_pipeline.py"))
        segments = work / "segments.json"
        engine = o.get("engine", "qwen")
        q = lambda v: "'" + str(v).replace("'", "'\\''") + "'"
        if engine == "qwen":
            self.wait_for_card(job, float(o.get("need_gib", 12)))
            job.report("Working out who spoke when")
            turns = work / "turns.json"
            r1 = self.wsl(f"{q(o['diar_python'])} {q(script)} diarize {q(wsl_path(audio))} {q(wsl_path(turns))} "
                          f"{q(o.get('diarizen_model', 'BUT-FIT/diarizen-wavlm-large-s80-md'))}", job)
            job.report(f"Transcribing {r1.get('speakers')} speakers")
            r2 = self.wsl(f"{q(o['qwen_python'])} {q(script)} turns {q(wsl_path(audio))} {q(wsl_path(turns))} "
                          f"{q(wsl_path(segments))} {q(o['qwen_model'])} {q(terms)}", job)
            stats = {"diarize_seconds": r1.get("seconds"), "transcribe_seconds": r2.get("seconds")}
        elif engine == "mlx":
            job.report("Working out who spoke when")
            turns = work / "turns.json"
            r1 = self.wsl(f"{q(o['python'])} {q(script)} sherpa {q(wsl_path(audio))} {q(wsl_path(turns))} "
                          f"{q(o['segmentation_model'])} {q(o['embedding_model'])} {q(o.get('diar_threshold', 0.4))}", job)
            job.report(f"Transcribing {r1.get('speakers')} speakers")
            r2 = self.wsl(f"{q(o['python'])} {q(script)} mlxturns {q(wsl_path(audio))} {q(wsl_path(turns))} "
                          f"{q(wsl_path(segments))} {q(o['asr_model'])} {q(terms)}", job)
            stats = {"diarize_seconds": r1.get("seconds"), "transcribe_seconds": r2.get("seconds")}
        elif engine == "vibevoice":
            self.wait_for_card(job, float(o.get("need_gib", 20)))
            job.report("Transcribing (who spoke, what and when)")
            r = self.wsl(f"{q(o['vibevoice_python'])} {q(script)} vibevoice {q(wsl_path(audio))} {q(wsl_path(segments))} "
                         f"{q(o['vibevoice_model'])} {q(terms)}", job)
            stats = {"transcribe_seconds": r.get("seconds")}
        elif engine == "nemotron":
            self.wait_for_card(job, float(o.get("need_gib", 29)))
            stats = self.nemotron(audio, segments, terms, job, script, q)
        else:
            raise ValueError(f"unknown engine {engine!r}")
        return json.loads(segments.read_text(encoding="utf-8")), stats

    def name_tags(self, video, segments, job):
        """Speaker names read off the video's name tags: {speaker: name}. Never fails the job: no OCR set up, or a step that
        errors, gives {} and the speakers keep their numbers."""
        o = self.options
        python = o.get("ocr_python") or (o.get("python") if o.get("engine") == "mlx" else None)
        if not python:
            return {}, {"name_tags": "not set up"}
        script = wsl_path(Path(__file__).with_name("meeting_pipeline.py"))
        out = segments.with_name("name-tags.json")
        q = lambda v: "'" + str(v).replace("'", "'\\''") + "'"
        job.report("Reading speaker names from the video")
        try:
            result = self.wsl(f"{q(python)} {q(script)} nametags {q(wsl_path(video))} {q(wsl_path(segments))} {q(wsl_path(out))}", job)
            tags = json.loads(out.read_text(encoding="utf-8"))
        except JobCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - names are a bonus
            return {}, {"name_tags": f"failed: {str(exc)[:300]}"}
        return {k: v["name"] for k, v in tags.items()}, {"name_tags_seconds": result.get("seconds"), "name_tag_frames": result.get("frames")}

    def nemotron(self, audio, segments, terms, job, script, q):
        o = self.options
        socket = o.get("socket", "/tmp/gs-meeting-nemotron.sock")
        serve_script = self.launch_dir / "meeting-nemotron-serve.sh"
        serve_script.write_text(NEMOTRON_SERVE.format(venv=o["nemotron_venv"], model=o["nemotron_model"], socket=socket,
                                                      util=o.get("gpu_memory_utilization", 0.88)),
                                encoding="utf-8", newline="\n")
        job.report("Starting the speech model (about 3-4 minutes)")
        started = time.time()
        server = threading.Thread(target=lambda: self._serve_until_done(serve_script, job), daemon=True)
        self._serving = threading.Event()
        self._server_error = None
        server.start()
        try:
            check = f"curl -s -m 5 --unix-socket {q(socket)} -o /dev/null -w '%{{http_code}}' http://localhost/health"
            while True:
                if job.cancel_requested:
                    raise JobCancelled()
                if self._server_error:
                    raise RuntimeError(f"The speech model did not start: {self._server_error}")
                if time.time() - started > float(o.get("start_timeout", 1500)):
                    raise TimeoutError("The speech model did not start in time")
                code = subprocess.run(["wsl.exe", "-d", self.distro, "--", "bash", "-lc", check],
                                      capture_output=True, text=True, timeout=30, check=False).stdout.strip()
                if code == "200":
                    break
                time.sleep(10)
            ready = time.time() - started
            job.report("Transcribing (who spoke, what and when)")
            r = self.wsl(f"{q(o['nemotron_python'])} {q(script)} nemotron {q(wsl_path(audio))} {q(wsl_path(segments))} "
                         f"{q(socket)} {q(terms)}", job)
            return {"engine_start_seconds": round(ready, 1), "transcribe_seconds": r.get("seconds")}
        finally:
            self._serving.set()  # ends the server: its heartbeat stops and the watchdog stops vLLM
            server.join(90)

    def _serve_until_done(self, serve_script, job):
        """Run the Nemotron server in WSL under its own heartbeat until the job is through with it."""
        beat = self.launch_dir / "meeting-heartbeat-server"
        argv = ["wsl.exe", "-d", self.distro, "--", "bash", wsl_path(self.watchdog), wsl_path(beat), "bash", "-lc",
                f"export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES={self.gpus[0]}; bash {wsl_path(serve_script)}"]
        log_path = self.launch_dir / "meeting-nemotron.log"
        with Heartbeat(beat) as heart, open(log_path, "a", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
            while not self._serving.wait(2):
                if process.poll() is not None:
                    tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
                    self._server_error = " | ".join(tail)[-400:] or f"exit {process.returncode}"
                    return
            heart.stop.set()  # stale heartbeat -> the watchdog stops vLLM within about 30 s
            process.terminate()
        deadline = time.time() + 120
        while time.time() < deadline and (self.card_free_gib() or 99) < float(self.options.get("need_gib", 29)) - 4:
            time.sleep(5)  # wait for the card to be handed back before the text model needs it


# ----- text model ----------------------------------------------------------------------------------------

def chat(model, prompt, max_tokens, thinking=True):
    body = {"model": model["model"], "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0.2, "stream": False}
    body.update(model.get("sampling") or {})
    body["temperature"] = 0.2
    if not thinking and model.get("thinking_floor"):  # always thinks: ask for the least it will do
        body["reasoning_effort"] = model["thinking_floor"]
    elif not thinking:
        body["enable_thinking"] = False
        body["reasoning_effort"] = "none"
    request = urllib.request.Request(model["base_url"].rstrip("/") + "/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        data = json.loads(response.read())
    return data["choices"][0]["message"].get("content") or ""


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def correct(model, segs, terms, job):
    """Correct recognition errors chunk by chunk. A turn whose length moves more than 30% keeps its original text."""
    out, changed, rejected, failed_chunks = [dict(s) for s in segs], 0, 0, 0
    i = 0
    while i < len(segs):
        j, words = i, 0
        while j < len(segs) and (words < CHUNK_WORDS or j == i):
            words += len(segs[j]["text"].split())
            j += 1
        job.report(f"Correcting the transcript ({100 * i // max(len(segs), 1)}%)")
        lines = "\n".join(f"{n}: {segs[n]['text']}" for n in range(i, j))
        prompt = CORRECT.format(lines=lines, terms=f"Names and terms that may occur: {terms}.\n" if terms else "")
        fixed = None
        for _ in range(2):
            try:
                fixed = {int(t["n"]): str(t["text"]) for t in parse_json(chat(model, prompt, words * 3 + 2048, thinking=False))["turns"]}
                break
            except Exception:  # noqa: BLE001, S112 - one retry, then this chunk keeps the recogniser's words
                continue
        if fixed is None:
            failed_chunks += 1
        for n in range(i, j):
            new, old = (fixed or {}).get(n), segs[n]["text"]
            if new is None or new == old:
                continue
            a, b = len(old.split()), len(new.split())
            if a and abs(b - a) / a > 0.3 and abs(b - a) > 2:
                rejected += 1
                continue
            out[n]["text"] = new
            changed += 1
        i = j
    return out, {"turns_corrected": changed, "corrections_refused": rejected, "chunks_not_corrected": failed_chunks}


def stamp(seg):
    return f"[{mmss(seg['start'])}] " if seg.get("start") is not None else ""


def extract(model, segs, people):
    transcript = "\n".join(f"{stamp(s)}{s['speaker']}: {s['text']}" for s in segs)
    prompt = EXTRACT.format(transcript=transcript,
                            people=f"The people in this meeting include: {people}.\n" if people else "")
    if any(s.get("start") is None for s in segs):  # a transcript that came without times
        prompt = (prompt.replace("[mm:ss] speaker: text", "speaker: text")
                  .replace("Times must point at the line that supports the item.", "The transcript has no times: use null for every time."))
    error = None
    for _ in range(2):
        try:
            # No thinking where the model allows it: on Qwen3.8-27B it spent all 8,000 tokens (498 s) reasoning before
            # any JSON. A model that always thinks (Inkling) ignores the request.
            # A model that always thinks (thinking_floor) spent 4,500 of 5,800 tokens on it for these notes: give it room.
            notes = parse_json(chat(model, prompt, 16000 if model.get("thinking_floor") else 8000, thinking=False))
            for key in ("summary", "actions", "decisions"):
                if not isinstance(notes.get(key), list):
                    raise TypeError(f"no {key} list")
            if not isinstance(notes.get("speakers"), dict):
                notes["speakers"] = {}
            notes["actions"] = [a for a in notes["actions"] if isinstance(a, dict) and a.get("task")]
            notes["decisions"] = [d for d in notes["decisions"] if isinstance(d, dict) and d.get("decision")]
            notes["summary"] = [str(b) for b in notes["summary"] if str(b).strip()]
            return notes
        except Exception as exc:  # noqa: BLE001 - one retry
            error = exc
    raise RuntimeError(f"The text model's notes could not be read ({error}).")


# ----- outputs ----------------------------------------------------------------------------------------------

def label_speakers(segs, names=None):
    """Speaker labels as Speaker 1, 2, ... in order of first appearance; a speaker read off the video by name keeps the
    name (two speakers with one name become one). The numbers count only the unnamed."""
    names, order, numbered = names or {}, {}, 0
    for s in segs:
        who = s["speaker"]
        if who in order:
            continue
        if names.get(who):
            order[who] = names[who]
        else:
            numbered += 1
            order[who] = f"Speaker {numbered}"
    return [dict(s, speaker=order[s["speaker"]]) for s in segs]


def write_outputs(job, segs, notes, names, raw):
    mimes = {"transcript.md": "text/markdown", "transcript.srt": "application/x-subrip", "transcript.vtt": "text/vtt"}
    for name, text in meeting_transcript.render(segs, names).items():
        job.output(name, mimes[name]).write_text(text, encoding="utf-8")
    if raw is not None:
        job.output("transcript-raw.json", "application/json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    record = {"speakers": names, "segments": segs, "revision": 1}
    if notes is not None:
        record.update({k: notes[k] for k in ("summary", "actions", "decisions")})
        mimes.update({"notes.md": "text/markdown", "actions.csv": "text/csv", "decisions.csv": "text/csv"})
        for name, text in meeting_transcript.render_notes(notes, names).items():
            with open(job.output(name, mimes[name]), "w", newline="", encoding="utf-8") as f:  # no newline translation: the CSVs end lines with \r\n
                f.write(text)
    job.output("meeting.json", "application/json").write_text(json.dumps(record, indent=1), encoding="utf-8")


# ----- gs_worker entry points -----------------------------------------------------------------------------------

def load(config, log=print):
    worker = Worker(config, log)
    worker.log(f"meeting notes: engine {worker.options.get('engine', 'qwen')} on GPU {worker.gpus[0]}")
    return worker


def generate(worker, inputs, job):
    recording = (inputs.get("recording") or [None])[0]
    if not recording:
        raise ValueError("Add a recording or a transcript.")
    terms = " ".join(str(inputs.get("terms") or "").split())[:500]
    people = " ".join(str(inputs.get("people") or "").split())[:500]
    raw = None
    if recording.get("kind") == "transcript":  # already transcribed: skip the audio steps
        job.report("Reading the transcript")
        try:
            segs, timed = meeting_transcript.parse(Path(recording["path"]).read_bytes().decode("utf-8-sig", errors="replace"))
        except meeting_transcript.TranscriptError as exc:
            raise ValueError(str(exc)) from exc
        if not timed:
            segs = [dict(s, start=None, end=None) for s in segs]
        job.detail(engine="transcript", speakers=len({s["speaker"] for s in segs}), segments=len(segs), timed=timed)
    else:
        work = job.dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        audio = work / "audio.wav"
        job.report("Preparing the audio")
        q = lambda v: "'" + str(v).replace("'", "'\\''") + "'"
        worker.wsl(f"ffmpeg -nostdin -hide_banner -loglevel error -y -i {q(wsl_path(recording['path']))} -vn -ac 1 -ar 16000 "
                   f"-c:a pcm_s16le {q(wsl_path(audio))} && echo '{{\"ok\": true}}'", job)
        started = time.time()
        raw, stats = worker.transcribe(audio, work, terms, job)
        stats["speech_seconds"] = round(time.time() - started, 1)
        if not raw:
            raise RuntimeError("No speech was found in the recording.")
        tags = {}
        if recording.get("kind") == "video" and inputs.get("video_names", "yes") == "yes":
            tags, tag_stats = worker.name_tags(Path(recording["path"]), work / "segments.json", job)
            stats.update(tag_stats)
        segs = label_speakers(raw, tags)
        job.detail(engine=worker.options.get("engine", "qwen"), speakers=len({s["speaker"] for s in segs}),
                   named_from_video=len(set(tags.values())), segments=len(segs),
                   audio_seconds=round(max(s["end"] for s in segs)), **stats)
        people = ", ".join(dict.fromkeys([p for p in [people, *tags.values()] if p]))[:500]
    notes, names, corrected = None, {}, False
    if inputs.get("notes", "notes") == "notes":
        job.report("Waiting for a text model")
        model = job.need("text_model", {"model": inputs.get("text_model") or "auto", "gpu": worker.gpus[0]})
        if not isinstance(model, dict) or model.get("error") or not model.get("base_url"):
            job.detail(notes_error=(model or {}).get("error") if isinstance(model, dict) else "no text model")
        else:
            job.detail(text_model=model.get("name"))
            t = time.time()
            if inputs.get("correct", "yes") == "yes" and model.get("can_correct", True):
                segs, cstats = correct(model, segs, terms, job)
                corrected = True
                job.detail(correct_seconds=round(time.time() - t, 1), **cstats)
            job.report("Writing the summary, action items and decisions")
            t = time.time()
            try:
                notes = extract(model, segs, people)
                names = {k: v.strip() for k, v in (notes.get("speakers") or {}).items()
                         if isinstance(v, str) and v.strip() and v.strip() != k}  # a name the file already gave needs no second one
                job.detail(notes_seconds=round(time.time() - t, 1), actions=len(notes["actions"]),
                           decisions=len(notes["decisions"]))
            except RuntimeError as exc:  # the transcript (corrected or not) is done and worth keeping
                job.detail(notes_error=str(exc), notes_seconds=round(time.time() - t, 1))
    write_outputs(job, segs, notes, names, raw if notes is not None or corrected else None)


if __name__ == "__main__":
    serve(load, generate)
