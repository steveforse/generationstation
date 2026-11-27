"""Turns a decision model's answers into the page a person reads: the answer, a probability bar for each option, how sure
the model is, and a note when the top two are close. Shared by the decision workers and their tests.

An answer is {"type": "choice"|"noul"|"score", ...} in TypeSafe's System One shape:
  choice: {"choice": name, "confidence": c, "probabilities": {name: p}}
  noul:   {"noul": p_yes, "confidence": c}
  score:  {"score": level index, "expected_level": x, "confidence": c, "probabilities": {"0": p, ...}}
"""
BAR = 20
CLOSE = 0.10  # the top two options are a "close call" when their probabilities differ by less than this


def bar(p: float) -> str:
    filled = max(0, min(BAR, round(p * BAR)))
    return "█" * filled + "░" * (BAR - filled)


def pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _table(rows):
    lines = ["| Option | Probability | |", "| --- | ---: | --- |"]
    lines += [f"| {name} | {pct(p)} | `{bar(p)}` |" for name, p in rows]
    return lines


def render(question: dict, answer: dict, *, model: str = "", seconds: float | None = None) -> str:
    """Markdown for one question and its answer. `question` is {"type", "instructions", "criteria"} as sent."""
    kind = answer.get("type") or question.get("type")
    lines = [f"**{question.get('instructions') or 'Question'}**", ""]
    confidence = answer.get("confidence")
    close = ""
    if kind == "choice":
        probabilities = answer.get("probabilities") or {}
        rows = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        lines += [f"Answer: **{answer.get('choice')}**", ""] + _table(rows)
        if len(rows) > 1 and rows[0][1] - rows[1][1] < CLOSE:
            close = f"Close call: {rows[0][0]} and {rows[1][0]} are within {int(CLOSE * 100)} points of each other."
    elif kind == "noul":
        yes = float(answer.get("noul", 0.0))
        lines += [f"Answer: **{'Yes' if yes >= 0.5 else 'No'}**", ""] + _table([("Yes", yes), ("No", 1 - yes)])
        if abs(yes - 0.5) < CLOSE / 2:
            close = "Close call: this is nearly a coin flip."
    elif kind == "score":
        labels = question.get("criteria") or []
        probabilities = answer.get("probabilities") or {}
        rows = [((labels[int(level)] if int(level) < len(labels) else f"Level {level}"), p) for level, p in sorted(probabilities.items(), key=lambda item: int(item[0]))]
        top = sorted(rows, key=lambda row: row[1], reverse=True)
        level = answer.get("score")
        name = labels[level] if isinstance(level, int) and level < len(labels) else level
        expected = answer.get("expected_level")
        lines += [f"Answer: **{name}**" + (f" (expected level {expected:.2f})" if isinstance(expected, (int, float)) else ""), ""] + _table(rows)
        if len(top) > 1 and top[0][1] - top[1][1] < CLOSE:
            close = f"Close call: {top[0][0]} and {top[1][0]} are within {int(CLOSE * 100)} points of each other."
    else:
        lines.append(f"Answer: {answer}")
    if isinstance(confidence, (int, float)):
        lines += ["", f"Confidence: **{pct(float(confidence))}**"]
    if close:
        lines += ["", f"_{close}_"]
    foot = " · ".join(part for part in (model, f"{seconds:.1f} s" if seconds is not None else "") if part)
    if foot:
        lines += ["", f"_{foot}_"]
    return "\n".join(lines) + "\n"


def render_all(questions: dict, answers: dict, *, model: str = "", seconds: float | None = None) -> str:
    """A page for several questions, each under its own heading when there is more than one."""
    parts = []
    for name, question in questions.items():
        body = render(question, answers[name], model="", seconds=None)
        parts.append((f"### {name}\n\n" if len(questions) > 1 else "") + body)
    foot = " · ".join(part for part in (model, f"{seconds:.1f} s" if seconds is not None else "") if part)
    if foot:
        parts.append(f"_{foot}_\n")
    return "\n".join(parts)
