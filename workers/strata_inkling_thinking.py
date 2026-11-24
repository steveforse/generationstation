"""Runs Strata's server with Inkling 2 Mini's thinking levels let through.

Strata's Inkling module (serve/inkling_dialect.py, Strata 0.2.19) treats the model as having no thinking mode: it
rewrites every request to effort "none" and drops whatever the model writes in its thinking channel. The model's own
chat template (in the pack's tokenizer folder) takes seven levels, none to max, as Basalt also documents. This wrapper
changes those three spots in memory and then starts Strata's server unchanged, so Strata's install is never edited and an
update to it keeps working (the wrapper refuses to start if the spots it changes are gone).

    python strata_inkling_thinking.py <Strata folder> <server.py arguments...>

A request without a level keeps Strata's behaviour (effort "none"), so callers that never ask for thinking see no change.
"""
import runpy
import sys
from pathlib import Path

LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def patch(dialect) -> None:
    for name in ("EFFORT", "DEFAULT_EFFORT", "normalize_effort", "template_kwargs", "InklingDialect"):
        if not hasattr(dialect, name):
            raise SystemExit(f"Strata's inkling_dialect has no {name}: this wrapper does not fit this Strata version.")
    if not hasattr(dialect.InklingDialect, "_emit_typed"):
        raise SystemExit("Strata's InklingDialect has no _emit_typed: this wrapper does not fit this Strata version.")
    dialect.EFFORT.update({level: level for level in LEVELS})

    def normalize_effort(value=None) -> str:
        key = str(dialect.DEFAULT_EFFORT if value is None else value).strip().lower()
        if key not in dialect.EFFORT:
            raise ValueError(f"unknown reasoning effort {value!r}: use {', '.join(LEVELS)}")
        return dialect.EFFORT[key]

    def template_kwargs(kwargs: dict) -> dict:
        out = dict(kwargs)
        out.pop("thinking_mode", None)
        off = out.pop("enable_thinking", True) is False
        out["reasoning_effort"] = "none" if off else normalize_effort(out.get("reasoning_effort"))
        return out

    original = dialect.InklingDialect._emit_typed

    def _emit_typed(self, chunk, out):
        if chunk and self.state == "think":
            out.append(("reasoning", chunk))
            return
        original(self, chunk, out)

    dialect.normalize_effort = normalize_effort
    dialect.template_kwargs = template_kwargs
    dialect.InklingDialect._emit_typed = _emit_typed


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path[:0] = [str(root / "tools"), str(root)]
    from serve import inkling_dialect
    patch(inkling_dialect)
    server = root / "serve" / "server.py"
    sys.argv = [str(server), *sys.argv[2:]]
    runpy.run_path(str(server), run_name="__main__")


if __name__ == "__main__":
    main()
