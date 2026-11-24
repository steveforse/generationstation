"""The wrapper that lets Inkling 2 Mini's thinking levels through Strata, against a stand-in of Strata's module."""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
import strata_inkling_thinking as wrapper


def strata_module():
    """Strata 0.2.19's inkling_dialect, reduced to what the wrapper changes."""
    dialect = types.ModuleType("inkling_dialect")
    dialect.DEFAULT_EFFORT = "none"
    dialect.EFFORT = {"none": "none", "off": "none", "false": "none"}
    dialect.normalize_effort = lambda value=None: "none"
    dialect.template_kwargs = lambda kwargs: {**kwargs, "enable_thinking": False, "reasoning_effort": "none"}

    class InklingDialect:
        def __init__(self):
            self.state = "idle"

        def _emit_typed(self, chunk, out):
            if self.state == "think":
                return  # Strata drops the thinking channel
            out.append(("content", chunk))

    dialect.InklingDialect = InklingDialect
    return dialect


def test_levels_reach_the_template_and_thinking_text_is_kept():
    dialect = strata_module()
    wrapper.patch(dialect)
    assert dialect.normalize_effort("High") == "high" and dialect.normalize_effort("off") == "none"
    assert dialect.template_kwargs({"reasoning_effort": "max"})["reasoning_effort"] == "max"
    assert dialect.template_kwargs({})["reasoning_effort"] == "none"  # no level asked: Strata's own default
    assert dialect.template_kwargs({"enable_thinking": False, "reasoning_effort": "high"})["reasoning_effort"] == "none"
    with pytest.raises(ValueError, match="unknown reasoning effort"):
        dialect.normalize_effort("ultra")
    parser, out = dialect.InklingDialect(), []
    parser.state = "think"
    parser._emit_typed("Let me see.", out)
    parser.state = "text"
    parser._emit_typed("Hi.", out)
    assert out == [("reasoning", "Let me see."), ("content", "Hi.")]


def test_a_strata_without_the_changed_spots_is_refused():
    dialect = strata_module()
    del dialect.normalize_effort
    with pytest.raises(SystemExit, match="normalize_effort"):
        wrapper.patch(dialect)
