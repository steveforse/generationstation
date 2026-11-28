"""One `make_song` chat tool for every running song model.

The model gives a style and, if it wants them, lyrics (empty for an instrumental), a length, a language, a tempo, a key, a time
signature, steps, a seed, an earlier song to start from (a new version of it, or a redone section) and which model. This module
picks the running model that can do it, picks the tab (a new song, a new version, or a redone section) and fills that tab's own
fields through the model's `music` capability (`plugins/music.py`), so the chat needs no tool per model. What a model cannot
take is left out and said in the result.
"""

WORDS = {"style": "the style", "lyrics": "the lyrics", "length": "the length", "language": "the language", "tempo": "the tempo",
         "key": "the key", "time_signature": "the time signature", "steps": "the steps", "strength": "how closely it follows the song",
         "start": "where the section starts", "end": "where the section ends"}


class SongTool:
    def __init__(self, fields_of=None):
        # fields_of(plugin, runtime, mode) -> {field key: InputSpec}; the chat gives the runtime's own (narrowed) form.
        self.fields_of = fields_of or (lambda plugin, runtime, mode: plugin.mode_inputs(mode or None, runtime) or {})

    def _spec(self, item, mode, role):
        _, runtime, plugin = item
        key = plugin.music.roles.get(mode, {}).get(role)
        return key, (self.fields_of(plugin, runtime, mode).get(key) if key else None)

    def _has(self, item, role, mode=None):
        return self._spec(item, item[2].music.create if mode is None else mode, role)[1] is not None

    def schema(self, running):
        """The tool for the song models running now (a list of (model_id, runtime, plugin)), or None."""
        if not running:
            return None
        lines = [("Make a song with a song model running now. Pass the style in `style` and the lyrics in `lyrics` (leave them out for an "
                  "instrumental); everything else is optional.")]
        for item in running:
            model_id, runtime, plugin = item
            info = plugin.music
            parts = []
            _, length = self._spec(item, info.create, "length")
            if length is not None:
                parts.append("length in seconds: " + (", ".join(length.options) if length.options else f"{length.minimum} to {length.maximum}"))
            else:
                parts.append("no length setting (the lyrics decide)")
            parts += [text for role, text in (("language", "language"), ("tempo", "tempo"), ("key", "key"), ("time_signature", "time signature"),
                                              ("steps", "steps")) if self._has(item, role)]
            if info.cover is not None:
                parts.append("a new version of an earlier song (`source_song`)")
            if info.repaint is not None:
                parts.append("redo a section of an earlier song, or extend it (`source_song` with `start` and `end`)")
            lines.append(f"- {runtime.name} (id {model_id}): {info.guidance} Takes: " + "; ".join(parts) + ".")
        properties = {
            "style": {"type": "string", "maxLength": 600, "description": "The genre, mood, instruments, voice and tempo, separated by commas."},
            "lyrics": {"type": "string", "maxLength": 4000, "description": "The lyrics, each part under a tag such as [Verse] or [Chorus]. Leave out for an instrumental."},
            "length": {"type": "integer", "description": "Seconds of music, for models that ask; the nearest length the model offers is used."},
            "language": {"type": "string", "description": "The language the lyrics are sung in (en, zh, ja, ko, es, fr, de, it, pt, ru), for models that ask."},
            "tempo": {"type": "integer", "description": "Beats per minute (30 to 300), for models that take one."},
            "key": {"type": "string", "description": "The musical key, such as \"A minor\" or \"C major\", for models that take one."},
            "time_signature": {"type": "string", "description": "2/4, 3/4, 4/4 or 6/8, for models that take one."},
            "steps": {"type": "integer", "description": "Refinement steps, for models that take them; leave out for the model's own."},
            "seed": {"type": "integer", "description": "A seed, to repeat a song."},
        }
        if any(item[2].music.cover is not None or item[2].music.repaint is not None for item in running):
            properties["source_song"] = {"type": "string", "description": "Reference (8 characters, such as 1a2b3c4d) of an earlier song to start from. Alone, the result is a new version of it in the given style; with `start` or `end`, only that section is redone."}
            properties["strength"] = {"type": "integer", "description": "With source_song: percent (5 to 100), how closely the new version follows the song. Default 50."}
            properties["start"] = {"type": "integer", "description": "With source_song: where in seconds the section to redo begins."}
            properties["end"] = {"type": "integer", "description": "With source_song: where it ends. Past the end of the song, the song is extended."}
        if len(running) > 1:
            properties["model"] = {"type": "string", "enum": [model_id for model_id, _, _ in running],
                                   "description": "Which model. Leave out to let the tool choose one that can do what was asked."}
        return {"type": "function", "function": {"name": "make_song", "description": "\n".join(lines)[:4000],
                                                 "parameters": {"type": "object", "properties": properties, "required": ["style"]}}}

    def plan(self, arguments, running):
        """(model_id, runtime, plugin, mode, inputs, references, notes) for a call, or ValueError saying what is wrong.
        `references` maps a files field to the result references to copy in."""
        style = arguments.get("style")
        if not isinstance(style, str) or not style.strip():
            raise ValueError("Give the style in `style`.")
        source = arguments.get("source_song")
        if source is not None and not isinstance(source, str):
            raise ValueError("`source_song` takes one result reference.")
        redo = source is not None and (arguments.get("start") is not None or arguments.get("end") is not None)
        by_id = {item[0]: item for item in running}
        asked = arguments.get("model")
        if asked is not None and asked not in by_id:
            raise ValueError(f"{asked} is not running. Running: {', '.join(by_id)}.")

        def tab(item):
            info = item[2].music
            return (info.repaint if redo else info.cover) if source else info.create

        if asked:
            chosen = by_id[asked]
        else:
            chosen = next((item for item in running if tab(item) is not None), None)
        if chosen is None or tab(chosen) is None:
            able = [r.name for _, r, p in running if (p.music.repaint if redo else p.music.cover) is not None]
            what = "redo a section of a song" if redo else "start from a song"
            who = f"{chosen[1].name} cannot {what}." if chosen else f"No running model can {what}."
            raise ValueError(who + (f" Use {' or '.join(able)}." if able else ""))
        model_id, runtime, plugin = chosen
        mode = tab(chosen)
        roles = plugin.music.roles[mode]
        form = self.fields_of(plugin, runtime, mode)
        values = {"style": style.strip(), "lyrics": (arguments.get("lyrics") or "").strip() or None, "length": arguments.get("length"),
                  "language": arguments.get("language"), "tempo": arguments.get("tempo"), "key": arguments.get("key"),
                  "time_signature": arguments.get("time_signature"), "steps": arguments.get("steps"), "seed": arguments.get("seed"),
                  "strength": arguments.get("strength") if source and not redo else None,
                  "start": arguments.get("start") if redo else None, "end": arguments.get("end") if redo else None}
        inputs = {"mode": mode} if plugin.modes else {}
        notes = []
        for role, value in values.items():
            if value in (None, ""):
                continue
            field = roles.get(role)
            if field is None or field not in form:
                if role != "style":
                    notes.append(f"{WORDS.get(role, role)} (this model has no place for it)")
                continue
            spec = form[field]
            if role == "length" and spec.options:  # the nearest length the model offers
                try:
                    value = min(spec.options, key=lambda option: abs(int(option) - int(value)))
                except (TypeError, ValueError):
                    notes.append("the length (it was not a number of seconds)")
                    continue
            inputs[field] = value
        references = {roles["source"]: [source]} if source else {}
        return model_id, runtime, plugin, mode, inputs, references, notes
