"""OmniVoice speech worker (k2-fsa/OmniVoice): text to speech in 600+ languages, cloning a voice from a short
sample or designing one from a description. Runs in its own environment (PyTorch, the `omnivoice` package).

Config options (from runtimes.json, per preset):
    model_dir   The k2-fsa/OmniVoice folder (model, tokenizers, audio_tokenizer/).
    asr_dir     Optional Whisper folder (openai/whisper-large-v3-turbo) used to transcribe a voice sample when no
                transcript is given; loaded the first time it is needed.

Inputs: mode ("clone" | "design"), prompt (the text to speak), sample ([{"path", ...}], clone), sample_text
    (clone, optional), design traits gender / age / pitch / accent ("any" or one of OmniVoice's English instruct
    items) and whisper ("no" | "yes"), language, speed ("slower" | "normal" | "faster"), quality, seed.
"""
import os
import random
import time

from gs_worker import serve

os.environ.setdefault("HF_HUB_OFFLINE", "1")

SAMPLE_RATE = 24000
SPEEDS = {"slower": 0.85, "normal": None, "faster": 1.15}
STEPS = {"standard": 32, "high": 64}


def voice_description(inputs):
    """OmniVoice's instruct text from the chosen traits ("female, young adult, british accent"); the plugin offers
    only items OmniVoice accepts. Jobs saved before the traits had a free-text "voice"."""
    items = [inputs.get(key) for key in ("gender", "age", "pitch", "accent")]
    items = [item for item in items if item and item != "any"]
    if inputs.get("whisper") == "yes":
        items.append("whisper")
    return ", ".join(items) or (inputs.get("voice") or "").strip()


def load(config, log=print):
    import torch
    from omnivoice import OmniVoice

    options = config["options"]
    started = time.perf_counter()
    extra = {"asr_model_name": options["asr_dir"]} if options.get("asr_dir") else {}
    model = OmniVoice.from_pretrained(options["model_dir"], device_map="cuda:0", dtype=torch.float16, **extra)
    log(f"[worker] OmniVoice ready in {time.perf_counter() - started:.1f} s, "
        f"{torch.cuda.memory_allocated() / 2**30:.1f} GiB on the card")
    return {"model": model, "torch": torch, "has_asr": bool(options.get("asr_dir"))}


def generate(state, inputs, job):
    import soundfile as sf

    torch, model = state["torch"], state["model"]
    mode = inputs.get("mode") or "design"
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    kwargs = {"text": inputs["prompt"], "language": (inputs.get("language") or "").strip() or None,
              "speed": SPEEDS.get(inputs.get("speed") or "normal"), "num_step": STEPS.get(inputs.get("quality") or "standard", 32)}
    if mode == "clone":
        sample = inputs["sample"][0]
        transcript = (inputs.get("sample_text") or "").strip() or None
        if transcript is None and not state["has_asr"]:
            raise ValueError("Type what is said in the voice sample (no transcriber is set up).")
        job.report("Listening to the voice sample" + ("" if transcript else " and writing down what it says"))
        kwargs.update(ref_audio=sample["path"], ref_text=transcript)
    else:
        voice = voice_description(inputs)
        if voice:
            kwargs["instruct"] = voice
    job.report("Speaking")
    torch.manual_seed(seed)
    try:
        audio = model.generate(**kwargs)[0]
    finally:
        torch.cuda.empty_cache()
    path = job.output(f"speech-{seed}.wav", "audio/wav")
    sf.write(str(path), audio, SAMPLE_RATE)
    job.detail(seed=seed, mode=mode, steps=kwargs["num_step"], audio_seconds=round(len(audio) / SAMPLE_RATE, 1),
               language=kwargs["language"] or "automatic", voice=kwargs.get("instruct"))
    job.report(f"Done: {len(audio) / SAMPLE_RATE:.0f} seconds of speech, seed {seed}")


def cleanup(state):
    state["torch"].cuda.empty_cache()


if __name__ == "__main__":
    serve(load, generate, cleanup=cleanup)
