"""The speech models' declared capabilities must agree with their own modes and fields."""
import pytest

from generationstation.plugins import get_plugin

SPEECH = ("qwen3_tts", "omnivoice", "fish_drama3", "fish_s2", "breeze_tts")


@pytest.mark.parametrize("kind", SPEECH)
def test_each_speech_plugin_declares_capabilities_that_match_its_fields(kind):
    plugin = get_plugin(kind)
    assert plugin.speech is not None
    assert plugin.speech.check(plugin) == []
    for mode, roles in plugin.speech.roles.items():
        assert "text" in roles, f"{kind}/{mode} has no text role"


def test_the_capabilities_say_who_can_do_what():
    info = {kind: get_plugin(kind).speech for kind in SPEECH}
    assert set(info["qwen3_tts"].voices) == {"builtin", "design", "clone"}
    assert "builtin" not in info["omnivoice"].voices and "own" not in info["omnivoice"].voices
    assert info["fish_drama3"].scene == "scene" and info["fish_s2"].scene is None
    # Clone is a voice source some model lacks, not an assumption: every voice source names a mode that really exists.
    for kind, speech in info.items():
        assert all(mode in get_plugin(kind).modes for mode in speech.voices.values())
    assert info["qwen3_tts"].direction.acts_emotion and info["fish_s2"].direction.acts_emotion
    assert not info["omnivoice"].direction.acts_emotion  # sounds only, and only its own list
    assert info["omnivoice"].direction.cues.open_vocabulary is False and info["fish_drama3"].direction.cues.open_vocabulary is True
