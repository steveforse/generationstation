"""Uploaded reference files: accepted types are checked by content, sizes are bounded, IDs cannot reach other files."""
import asyncio

import pytest

from generationstation.uploads import MAX_BYTES, UploadError, UploadStore

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def stream(*chunks):
    for chunk in chunks:
        yield chunk


def test_saves_a_picture_and_finds_it_again(tmp_path):
    store = UploadStore(tmp_path)
    record = asyncio.run(store.save_stream("My Cat (1).PNG", stream(PNG[:10], PNG[10:])))
    assert record["kind"] == "image" and record["mime"] == "image/png" and record["bytes"] == len(PNG)
    assert record["name"] == "My-Cat-1.png"
    found = store.get(record["id"])
    assert found["kind"] == "image"
    name = store.copy_to(found, tmp_path / "job" / "inputs", 1)
    assert name == "01-My-Cat-1.png" and (tmp_path / "job" / "inputs" / name).read_bytes() == PNG


@pytest.mark.parametrize("name, data, message", [
    ("notes.exe", b"hello", "not accepted"),
    ("call.vtt", b"WEBVTT\n\x00\x01", "not a valid"),
    ("photo.png", b"GIF89a....", "not a valid PNG"),
    ("clip.mp4", b"\x00\x00\x00\x18notftyp", "not a valid MP4"),
    ("empty.wav", b"", "not a valid WAV"),
])
def test_refuses_wrong_or_disguised_files(tmp_path, name, data, message):
    with pytest.raises(UploadError, match=message):
        UploadStore(tmp_path).save(name, [data])
    assert list((tmp_path / "uploads").glob("*")) == []  # no partial file is left behind


def test_refuses_files_over_the_limit(tmp_path):
    big = [PNG] + [b"\x00" * (1024 * 1024)] * (MAX_BYTES["image"] // (1024 * 1024) + 1)
    with pytest.raises(UploadError, match="too large"):
        asyncio.run(UploadStore(tmp_path).save_stream("huge.png", stream(*big)))
    assert list((tmp_path / "uploads").glob("*")) == []


def test_ids_are_only_upload_ids(tmp_path):
    store = UploadStore(tmp_path)
    for bad in ("../runtimes", "a" * 31, None, 5, "A" * 32):
        assert store.get(bad) is None


def test_a_transcript_is_kept_as_text_and_a_binary_one_is_refused(tmp_path):
    store = UploadStore(tmp_path)
    record = store.save("Standup.VTT", ["WEBVTT\n\n00:00.000 --> 00:02.000\nAnna: héllo\n".encode()])
    assert record["kind"] == "transcript" and record["mime"] == "text/vtt"
    assert store.save("notes.md", [b"# Notes\nAnna: hi"])["kind"] == "transcript"
    with pytest.raises(UploadError):
        store.save("call.txt", [b"\xff\xfe\x00\x00binary"])
