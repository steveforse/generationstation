"""One `transcribe` chat tool for every running speech-to-text model.

The model names an earlier recording (a clip, a song, a voice recording, a meeting) by its reference and, if it wants them, a language,
words to expect, whether to label the speakers, and which model. This module picks the running model that can do it and fills that
model's own fields through its `transcribe` capability (`plugins/transcribe.py`), so the chat needs no tool per model. What a model
cannot take is left out and said in the result.
"""

# The order a model is picked in when none is named: the most accurate first.
ORDER = ("qwen3_asr", "whisper_asr", "parakeet_asr")
WORDS = {"language": "the language", "terms": "the words to expect", "speakers": "who spoke"}


class TranscribeTool:
    def __init__(self, fields_of=None):
        # fields_of(plugin, runtime) -> {field key: InputSpec}; the chat gives the runtime's own (narrowed) form.
        self.fields_of = fields_of or (lambda plugin, runtime: plugin.mode_inputs(None, runtime) or {})

    def _has(self, item, role):
        _, runtime, plugin = item
        key = plugin.transcribe.roles.get("", {}).get(role)
        return bool(key) and key in self.fields_of(plugin, runtime)

    def schema(self, running):
        """The tool for the speech-to-text models running now (a list of (model_id, runtime, plugin)), or None."""
        if not running:
            return None
        lines = [("Write down what is said in an earlier result (a video, a song, a recording, a meeting) or in a file attached to the chat. "
                  "Pass the result's reference in `recording`. The transcript is shown in the chat when it is done.")]
        for item in running:
            model_id, runtime, plugin = item
            info = plugin.transcribe
            takes = [text for role, text in (("language", "a language"), ("terms", "words to expect"), ("speakers", "who spoke")) if self._has(item, role)]
            lines.append(f"- {runtime.name} (id {model_id}): {info.guidance} {'With times.' if info.times == 'lines' else 'No times.'}"
                         + (f" Takes: {', '.join(takes)}." if takes else ""))
        properties = {
            "recording": {"type": "string", "description": "Reference (8 characters, such as 1a2b3c4d) of the earlier result to write down."},
            "language": {"type": "string", "description": "The language spoken (English, Spanish, French, ...), for models that ask; leave out to detect it."},
            "terms": {"type": "string", "description": "Names and terms that come up, separated by commas, for models that take them."},
            "speakers": {"type": "boolean", "description": "True to label who spoke (Speaker 1, Speaker 2, ...), for models that can. Slower."},
        }
        if len(running) > 1:
            properties["model"] = {"type": "string", "enum": [model_id for model_id, _, _ in running],
                                   "description": "Which model. Leave out to let the tool choose one that can do what was asked."}
        return {"type": "function", "function": {"name": "transcribe", "description": "\n".join(lines)[:4000],
                                                 "parameters": {"type": "object", "properties": properties, "required": ["recording"]}}}

    def plan(self, arguments, running):
        """(model_id, runtime, plugin, mode, inputs, references, notes) for a call, or ValueError saying what is wrong."""
        recording = arguments.get("recording")
        if not isinstance(recording, str) or not recording.strip():
            raise ValueError("Give the reference of the recording in `recording`.")
        by_id = {item[0]: item for item in running}
        asked = arguments.get("model")
        if asked is not None and asked not in by_id:
            raise ValueError(f"{asked} is not running. Running: {', '.join(by_id)}.")
        wants = [role for role, key in (("language", "language"), ("speakers", "speakers")) if arguments.get(key) not in (None, "", False)]
        if asked:
            chosen = by_id[asked]
        else:
            ranked = sorted(running, key=lambda item: ORDER.index(item[2].kind) if item[2].kind in ORDER else len(ORDER))
            chosen = max(ranked, key=lambda item: sum(self._has(item, role) for role in wants))  # the most accurate that takes what was asked
        model_id, runtime, plugin = chosen
        form = self.fields_of(plugin, runtime)
        roles = plugin.transcribe.roles[""]
        values = {"language": arguments.get("language"), "terms": arguments.get("terms"),
                  "speakers": {True: "yes", False: None}.get(arguments.get("speakers"))}
        inputs, notes = {}, []
        for role, value in values.items():
            if value in (None, ""):
                continue
            field = roles.get(role)
            if field is None or field not in form:
                notes.append(f"{WORDS[role]} (this model has no place for it)")
                continue
            spec = form[field]
            if role == "language" and spec.options:
                match = next((option for option in spec.options if option.lower() == str(value).strip().lower()), None)
                if match is None:
                    notes.append(f"the language (this model does not list {value})")
                    continue
                value = match
            inputs[field] = value
        return model_id, runtime, plugin, "", inputs, {roles["recording"]: [recording.strip()]}, notes
