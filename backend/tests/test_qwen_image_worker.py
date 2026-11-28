"""The Apple-silicon picture worker's pieces that do not need mflux: sizes, command families and the arguments it gives mflux's parsers."""
import sys

import pytest

from generationstation.plugins.worker import WORKERS_DIR


@pytest.fixture
def worker():
    sys.path.insert(0, str(WORKERS_DIR))
    try:
        import qwen_image_mflux_worker
        yield qwen_image_mflux_worker
    finally:
        sys.path.remove(str(WORKERS_DIR))


def test_sizes(worker):
    assert worker._size("wide") == (1344, 768) and worker._size("1290x730") == (1280, 720)
    with pytest.raises(ValueError, match="between 256 and 2048"):
        worker._size("100x100")


def test_each_command_names_a_family_and_unknown_ones_are_refused(worker):
    assert worker._family({}) == "qwen21"
    assert worker._family({"command": "mflux-generate-qwen"}) == "qwen"
    assert worker._family({"command": "/x/bin/mflux-generate-z-image-turbo"}) == "zimage"
    with pytest.raises(ValueError, match="Unknown mflux command"):
        worker._family({"command": "mflux-generate"})


def test_the_parser_reads_the_arguments_put_in_argv_and_argv_is_restored(worker):
    class Parser:
        def parse_args(self):
            return list(sys.argv)

    before = list(sys.argv)
    argv = [*worker._base_args({"model_dir": "/m", "base_model": "qwen-image"}), "--prompt", "a fox"]
    assert worker._parse(Parser(), argv) == ["mflux", "--model", "/m", "--base-model", "qwen-image", "--prompt", "a fox"]
    assert sys.argv == before
