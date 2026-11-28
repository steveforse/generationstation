"""One `speak` chat tool for every running speech model.

The model gives the words and, if it wants them, a saved voice, a described voice, a built-in speaker, a direction in plain
words, a language, a speed and a seed. This module picks the running model that can do it, picks the tab that serves the voice
source, and fills that tab's own fields through the model's `speech` capability (`plugins/speech.py`), so the chat needs no
tool per model. What a model cannot take is left out and said in the result; cues the model would read aloud are removed.
"""
import re

SQUARE = re.compile(r"\[[^\[\]]*\]")
LIMIT = 4000


def _cue_pattern(cues):
    return re.compile(f"{re.escape(cues.open)}[^{re.escape(cues.open)}{re.escape(cues.close)}]*{re.escape(cues.close)}")


class SpeakTool:
    def __init__(self, voices=None):
        self.voices = voices

    def saved(self) -> list[dict]:
        return self.voices.list() if self.voices else []

    # ----- what the model is told ---------------------------------------------------------------

    def schema(self, running):
        """The tool for the speech models running now (a list of (model_id, runtime, plugin)), or None."""
        if not running:
            return None
        lines = ["Speak text aloud with a speech model running now. Pass the words in `text`; everything else is optional."]
        for model_id, runtime, plugin in running:
            info = plugin.speech
            sources = {"builtin": "built-in speakers", "design": "a voice described in words", "clone": "a saved voice", "own": "its own voice"}
            lines.append(f"- {runtime.name} (id {model_id}): " + ", ".join(sources[source] for source in info.voices) + ". " + info.direction.text)
            cues = info.direction.cues
            if cues:
                lines.append(f"  Cues in the text: {cues.text} {', '.join(cues.examples)}" + ("" if cues.open_vocabulary else " (only these)") + ".")
            else:
                lines.append("  Do not put [bracketed] cues in the text for this model: it would read them aloud.")
        voices = self.saved()
        if voices:
            lines.append("Saved voices (pass the name as `voice`): " + ", ".join(voice["name"] for voice in voices) + ".")
        properties = {
            "text": {"type": "string", "maxLength": 5000, "description": "The words to say."},
            "voice": {"type": "string", "description": "The name of a saved voice to speak in." + (" One of: " + ", ".join(voice["name"] for voice in voices) if voices else " None are saved.")},
            "voice_description": {"type": "string", "description": "A voice described in words (age, gender, tone), for models that take one."},
            "builtin_voice": {"type": "string", "description": "A built-in speaker's name, for models that have them."},
            "direction": {"type": "string", "description": "How to say it, in plain words (angry and fast, whispering), for models that take direction."},
            "language": {"type": "string", "description": "The language, for models that ask."},
            "speed": {"type": "number", "description": "Speaking speed, 1.0 is normal, for models that take it."},
            "seed": {"type": "integer", "description": "A seed, to repeat a take."},
        }
        if len(running) > 1:
            properties["model"] = {"type": "string", "enum": [model_id for model_id, _, _ in running], "description": "Which speech model. Leave out to let the tool choose one that can do what was asked."}
        return {"type": "function", "function": {"name": "speak", "description": "\n".join(lines)[:LIMIT],
                                                 "parameters": {"type": "object", "properties": properties, "required": ["text"]}}}

    # ----- a call -------------------------------------------------------------------------------

    def plan(self, arguments, running, uploads):
        """(model_id, runtime, inputs, notes) for a call, or ValueError saying what is wrong."""
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Give the words to say in `text`.")
        voice = self._voice(arguments.get("voice"))
        described, builtin = _words(arguments.get("voice_description")), _words(arguments.get("builtin_voice"))
        by_id = {model_id: (model_id, runtime, plugin) for model_id, runtime, plugin in running}
        asked = arguments.get("model")
        if asked is not None and asked not in by_id:
            raise ValueError(f"{asked} is not running. Running: {', '.join(by_id)}.")
        if asked:
            chosen = by_id[asked]
        else:
            wanted = "clone" if voice else "design" if described else "builtin" if builtin else None
            chosen = next((item for item in running if wanted in item[2].speech.voices), running[0]) if wanted else running[0]
        model_id, runtime, plugin = chosen
        info = plugin.speech
        notes = []
        if voice and "clone" not in info.voices:
            able = [r.name for _, r, p in running if "clone" in p.speech.voices]
            raise ValueError(f"{runtime.name} cannot speak in a saved voice." + (f" Use {' or '.join(able)}." if able else " No running model can."))
        source = ("clone" if voice else "design" if described and "design" in info.voices else "builtin" if "builtin" in info.voices else
                  "own" if "own" in info.voices else "design" if "design" in info.voices else "clone")
        if described and source != "design":
            notes.append("the voice description (this model, or the voice chosen, has no place for it)")
        if builtin and source != "builtin":
            notes.append("the built-in speaker")
        mode = info.voices[source]
        roles = info.roles[mode]
        values = {"text": self._clean(text, info, runtime.name, notes), "language": arguments.get("language"), "seed": arguments.get("seed"),
                  "speed": arguments.get("speed"), "direction": _words(arguments.get("direction")), "builtin_voice": builtin if source == "builtin" else None,
                  "voice_description": described if source == "design" else None}
        inputs = {"mode": mode} if plugin.modes else {}
        for role, value in values.items():
            if value in (None, ""):
                continue
            if role in roles:
                inputs[roles[role]] = value
            elif role in {"direction", "speed", "language", "seed"}:
                notes.append(f"the {role} (this model has no place for it)")
        if voice:
            path, _, name = self.voices.sample_path(voice["id"])
            inputs[roles["sample"]] = [uploads.save(name, _chunks(path))["id"]]
            if voice["sample_text"] and "sample_text" in roles:
                inputs[roles["sample_text"]] = voice["sample_text"]
        return model_id, runtime, inputs, notes

    def _voice(self, name):
        if name in (None, ""):
            return None
        for voice in self.saved():
            if voice["name"].casefold() == str(name).strip().casefold():
                return voice
        known = ", ".join(voice["name"] for voice in self.saved())
        raise ValueError(f"There is no saved voice named {name!r}." + (f" Saved: {known}." if known else " None are saved."))

    @staticmethod
    def _clean(text, info, name, notes):
        """The text without cues this model would read aloud (or refuse)."""
        cues = info.direction.cues
        if cues is None or cues.open != "[":
            found = SQUARE.findall(text)
            if found:
                notes.append(f"the cues {' '.join(found)} ({name} would read them aloud)")
                text = SQUARE.sub("", text)
        elif not cues.open_vocabulary:
            known = {example.lower() for example in cues.examples}
            unknown = [found for found in _cue_pattern(cues).findall(text) if found.lower() not in known]
            if unknown:
                notes.append(f"the cues {' '.join(unknown)} ({name} does not know them)")
                for found in unknown:
                    text = text.replace(found, "")
        return re.sub(r"[ \t]{2,}", " ", text).replace(" ,", ",").strip()


def _words(value):
    return " ".join(value.split()) if isinstance(value, str) else None


def _chunks(path):
    with open(path, "rb") as handle:
        while block := handle.read(1024 * 1024):
            yield block

