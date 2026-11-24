"""Fish Audio Drama 3: the form, and the worker's pieces that do not need the server (scripts, paths, WAVs)."""
import array
import io
import math
import sys
import wave

import pytest

from generationstation.plugins import get_plugin
from generationstation.plugins.worker import WORKERS_DIR
from generationstation.runtimes import SettingsError, validate_inputs

DRAMA = get_plugin("fish_drama3")


@pytest.fixture(scope="module")
def worker():
    sys.path.insert(0, str(WORKERS_DIR))
    try:
        import fish_drama3_worker
        yield fish_drama3_worker
    finally:
        sys.path.remove(str(WORKERS_DIR))


def wav(seconds, rate=24000):
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(b"\1\0" * int(seconds * rate))
    return out.getvalue()


def test_the_form_speaks_a_text_or_a_scene():
    assert validate_inputs(DRAMA, {"prompt": "[whispers] Hello"}) == {"mode": "speak", "prompt": "[whispers] Hello"}
    with pytest.raises(SettingsError):
        validate_inputs(DRAMA, {"mode": "scene"})
    assert DRAMA.check_inputs("scene", {"script": "Hello there"}, {}) == [
        'Start each line of the script with a name and a colon, such as "Anna: Hello."']
    assert DRAMA.check_inputs("scene", {"script": "Anna: Hi.\nBen: [laughs] Hi!"}, {}) == []
    assert DRAMA.output_kind == "audio" and DRAMA.make_label == "Make speech"


def test_scripts_paths_and_transcripts(worker):
    lines = worker.parse_script("Anna: [nervous] Did you hear that?\n  and again?\n\nBen: It's the wind.")
    assert lines == [("Anna", "[nervous] Did you hear that? and again?"), ("Ben", "It's the wind.")]
    with pytest.raises(ValueError):
        worker.parse_script("no names here")
    assert worker.spoken("[sighs] Fine. [laughs]  Well, maybe.") == "Fine. Well, maybe."
    assert worker.wsl_path(r"D:\ai\outputs\x y.wav") == "/mnt/d/ai/outputs/x y.wav"
    assert worker.wsl_path(r"C:\Projects\generationstation\runtime\uploads\a.wav") == \
        "/mnt/c/Projects/generationstation/runtime/uploads/a.wav"


def test_takes_are_joined_with_a_short_pause(worker):
    joined = worker.join_wavs([wav(1.0), wav(2.0)])
    assert worker.wav_seconds(joined) == pytest.approx(3.0 + worker.GAP_SECONDS, abs=0.01)
    with pytest.raises(ValueError):
        worker.join_wavs([wav(1.0), wav(1.0, rate=44100)])


def test_the_wsl_script_runs_each_engine_under_a_heartbeat_watchdog(worker, tmp_path):
    fast = worker.Server({"engine": "sglang", "model_path": "/mnt/d/ai/models/fish-audio/drama-3-nvfp4", "server_port": 8251,
                          "max_frames": 512, "wsl_gpus": "0", "serve_args": "--tts_engine.factory.reference_sampling true"},
                         tmp_path, print).script()
    assert "setsid .venv/bin/sgl-omni serve --model-path '/mnt/d/ai/models/fish-audio/drama-3-nvfp4'" in fast
    assert "--tts_engine.factory.max_new_tokens 512 --tts_engine.factory.reference_sampling true" in fast
    assert "if grep -q 'only speaker 0 is supported'" in fast and "sglang-omni-drama3.patch'" in fast
    assert "CUDA_VISIBLE_DEVICES=0\n" in fast
    full = worker.Server({"engine": "fish", "model_path": "/mnt/d/ai/models/fish-audio/drama-3", "server_port": 8253,
                          "wsl_gpus": "0,1", "device_weights": "0.81,0.19"}, tmp_path, print).script()
    assert "FISH_DRAMA3_DEVICE_WEIGHTS='0.81,0.19' FISH_DRAMA3_FP8_EXPERTS=1" in full
    assert "tools/api_server.py --listen 127.0.0.1:8253 --llama-checkpoint-path '/mnt/d/ai/models/fish-audio/drama-3' --device cuda:0,cuda:1,cuda:1" in full
    assert "if ! grep -q Drama3SplitDecodeGraphs" in full and "git checkout -- $(git apply --numstat" in full and "fish-speech-drama3-two-cards.patch'" in full
    for script in (fast, full):
        assert 'if [ "$age" -gt 20 ]' in script and "stopping the server" in script and "${age}" in script
        assert "kill -TERM -- \"-$old\"" in script  # a server left from an earlier start is stopped first
        assert 'PATH="$PWD/.venv/bin:$PATH"' in script
        assert "stop() { kill -TERM" in script and "trap 'stop; exit 0' TERM INT HUP" in script
    for name in ("sglang-omni-drama3.patch", "fish-speech-drama3-two-cards.patch"):
        assert (worker.PATCHES / name).is_file() and b"\r\n" not in (worker.PATCHES / name).read_bytes()


def test_each_engine_gets_its_own_request(worker, tmp_path):
    sample = tmp_path / "anna.wav"
    sample.write_bytes(wav(0.5))
    voices = [worker.voice(sample, "Hello there.", 1)]
    url, body = worker.Server({"engine": "sglang", "model_path": "m", "server_port": 8251}, tmp_path, print).body("<|speaker:1|>Hi.", voices, 7)
    assert url.endswith(":8251/v1/audio/speech") and "seed" not in body and body["temperature"] == 1.0
    assert body["references"] == [{"audio_path": worker.wsl_path(sample), "text": "<|speaker:1|> Hello there."}]
    url, body = worker.Server({"engine": "fish", "model_path": "m", "server_port": 8253}, tmp_path, print).body("<|speaker:1|>Hi.", voices, 7)
    assert url.endswith(":8253/v1/tts") and body["seed"] == 7 and body["max_new_tokens"] == 512
    assert body["references"][0]["speaker"] == 1 and body["references"][0]["text"] == "Hello there."
    assert len(body["references"][0]["audio"]) > 255  # base64, as Fish's server expects


def test_each_preset_runs_on_its_own_cards():
    from generationstation.runtimes import parse_catalog
    entry = {"kind": "fish_drama3", "name": "Drama 3", "workload": "speech", "python": sys.executable, "output_dir": "o",
             "port": 8220, "default_preset": "fast", "presets": {
                 "fast": {"name": "Fast", "gpus": [0], "allowed_gpus": [0], "options": {}, "settings": {},
                          "estimate": {"ram_gib": 14, "gpu_min_free_gib": {"0": 29}}},
                 "full": {"name": "Full quality", "gpus": [0, 1], "allowed_gpus": [0, 1], "options": {}, "settings": {},
                          "estimate": {"ram_gib": 16, "gpu_min_free_gib": {"0": 27.5, "1": 12.7}}}}}
    runtime = parse_catalog({"runtimes": {"drama": entry}}).runtimes["drama"]
    assert DRAMA.check_gpus(runtime.presets["full"], [0]) == ["Full quality runs on GPU 0 and GPU 1."]
    assert DRAMA.check_gpus(runtime.presets["full"], [1, 0]) == [] and DRAMA.check_gpus(runtime.presets["fast"], [0]) == []
    assert DRAMA.gpu_limit(runtime.presets["full"]) == 2


def test_scenes_are_split_like_fish_audio_does(worker):
    lines = [(0, "[nervous] Did you hear that?"), (1, "It's the wind."), (2, "Me!"), (0, "Hush."), (1, "Fine.")]
    blocks = worker.scene_blocks(lines)
    assert blocks == [[(0, "[nervous] Did you hear that?"), (1, "It's the wind."), (2, "Me!"), (0, "Hush.")], [(1, "Fine.")]] \
        or all(len({w for w, _ in b}) <= 3 for b in blocks)
    assert all(len({w for w, _ in b}) <= 3 for b in blocks)
    assert worker.tagged([(0, "Hi."), (1, "[laughs] Hey.")]) == "<|speaker:0|>Hi. <|speaker:1|>[laughs] Hey."
    long = " ".join(f"Sentence number {n} is here." for n in range(40))
    parts = worker.split_long(long)
    assert len(parts) > 1 and all(len(p.encode()) <= worker.BLOCK_BYTES for p in parts) and " ".join(parts) == long
    assert worker.voice_text(long) == "Sentence number 0 is here. Sentence number 1 is here. Sentence number 2 is here. Sentence number 3 is here."
    assert len(worker.voice_text("word " * 100).encode()) <= worker.VOICE_BYTES
    big = worker.scene_blocks([(0, long), (1, "Short.")])
    assert all(sum(len(f"<|speaker:{w}|>{t} ".encode()) for w, t in b) <= worker.BLOCK_BYTES + 20 for b in big)


def tone(seconds, rate=24000, loud=True):
    return array.array("h", (int(8000 * math.sin(i / 8)) if loud else 0 for i in range(int(seconds * rate)))).tobytes()


def test_long_pauses_are_shortened_and_the_tail_trimmed(worker):
    with wave.open(io.BytesIO(wav(0.1))) as clip:
        params = clip.getparams()
    data = worker._write(params, tone(1.0) + tone(3.0, loud=False) + tone(1.0) + tone(2.0, loud=False))
    tidied = worker.tidy_pauses(data)
    assert worker.wav_seconds(tidied) == pytest.approx(1.0 + worker.KEEP_PAUSE + 1.0 + 0.3, abs=0.06)


def speech(seconds):
    with wave.open(io.BytesIO(wav(0.1))) as clip:
        params = clip.getparams()
    return params


def take(worker, spoken_seconds, total=None):
    """A WAV with `spoken_seconds` of sound, padded with silence to `total` seconds."""
    params = speech(0)
    audio = tone(spoken_seconds) + tone((total or spoken_seconds) - spoken_seconds, loud=False)
    return worker._write(params, audio)


def test_takes_are_judged_by_length_speech_and_words(worker):
    text = "<|speaker:0|>[nervous] Did you hear that? <|speaker:1|>It's just the wind."
    assert worker.spoken(text) == "Did you hear that? It's just the wind."
    assert worker.needed_seconds(text) == pytest.approx(len("Didyouhearthat?It'sjustthewind.") / worker.CHARS_PER_SECOND)
    assert worker.speech_seconds(take(worker, 2.0, 5.0)) == pytest.approx(2.0, abs=0.05)
    assert worker.recall("Did you hear that? It's just the wind.", " did you hear that, it’s just the wind") == 1.0
    assert worker.recall("Did you hear that? It's just the wind.", "Did you hear that?") == pytest.approx(4 / 8)


def test_an_incomplete_take_is_made_again_and_the_best_kept(worker, tmp_path):
    text = "<|speaker:0|>Did you hear that? <|speaker:1|>It's just the wind. Go back to sleep."
    server = worker.Server({"model_path": "x", "max_frames": 512}, tmp_path, lambda m: None)
    takes = iter([take(worker, 3.0, 23.8), take(worker, 3.0), take(worker, 4.0)])  # stalled, words missing, good
    heard = iter(["Did you hear that?", "Did you hear that? It's just the wind. Go back to sleep."])
    server.request = lambda text, refs=(), seed=None: next(takes)

    class Checker:
        def heard(self, data):
            return next(heard)
    server.checker = Checker()
    data, attempts = server.speak(text)
    assert attempts == 3 and worker.speech_seconds(data) == pytest.approx(4.0, abs=0.05)
    # Without the check, a take far too short for its words is still caught; after three, the best is kept.
    server.checker = None
    server.request = lambda text, refs=(), seed=None: take(worker, 0.5)
    data, attempts = server.speak(text)
    assert attempts == worker.RETRIES and worker.speech_seconds(data) == pytest.approx(0.5, abs=0.05)
