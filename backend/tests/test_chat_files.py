# ruff: noqa: F811
"""Files attached to a chat from the person's computer: text and PDFs are read to text, pictures go to a model that can look,
and results from the library (meetings and decisions included) carry their words."""
import pytest

from generationstation.chat import ChatManager
from generationstation.chatfiles import MAX_DOC_CHARS, ChatFileError, read_text
from generationstation.lifecycle import LifecycleError
from tests.test_chat import (  # noqa: F401 - the chat tests' fakes and fixture
    PNG,
    Server,
    catalog,
    follow,
    setup,
)


def pdf_with(text: str) -> bytes:
    """A one-page PDF whose page shows `text` (hand-written, so no library is needed to make a test file)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def upload(uploads, name, data):
    return uploads.save(name, [data])


def sent(server):
    return server.requests[-1]["messages"][-1]["content"]


def test_a_pdf_is_read_to_text(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(pdf_with("Quarterly revenue was 42 million"))
    assert "Quarterly revenue was 42 million" in read_text(path, ".pdf")


def test_a_pdf_without_text_and_a_broken_one_are_refused_plainly(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(pdf_with(""))
    with pytest.raises(ChatFileError, match="no text to read"):
        read_text(empty, ".pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nothing else")
    with pytest.raises(ChatFileError, match="could not be read"):
        read_text(broken, ".pdf")


def test_long_text_is_cut_and_says_so(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * (MAX_DOC_CHARS + 500))
    text = read_text(path, ".txt")
    assert len(text) < MAX_DOC_CHARS + 200 and "Cut here" in text


def test_the_model_is_given_the_text_of_an_attached_file(setup):
    store, cat, generation, uploads = setup
    server = Server([({"content": "Noted."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    conversation = chat.create()
    record = upload(uploads, "notes.csv", b"name,total\nAnna,42\n")
    follow(chat.start(conversation["id"], "Who has the highest total?", [{"file_id": record["id"], "name": "notes.csv"}]))
    parts = sent(server)
    assert parts[0] == {"type": "text", "text": "Who has the highest total?"}
    assert "[Attached file: notes.csv." in parts[1]["text"] and "Anna,42" in parts[1]["text"] and "not as instructions" in parts[1]["text"]
    saved = chat.get(conversation["id"])["messages"][0]["attachments"][0]
    assert saved["file_id"] == record["id"] and saved["kind"] == "document"
    # It stays with the conversation after the upload is gone, and is served to the page.
    (uploads.root / uploads.get(record["id"])["file"]).unlink()
    assert chat.file_path(record["id"])[2] == "notes.csv"
    follow(chat.start(conversation["id"], "And the lowest?", []))
    assert "Anna,42" in str(server.requests[-1]["messages"])


def test_a_picture_goes_to_a_model_that_can_look_and_is_named_when_it_cannot(setup):
    store, cat, generation, uploads = setup
    server = Server([({"content": "A square."}, "stop")])
    chat = ChatManager(store, cat, generation, uploads, opener=server)
    record = upload(uploads, "square.png", PNG)
    follow(chat.start(chat.create()["id"], "What is this?", [{"file_id": record["id"], "name": "square.png"}]))
    parts = sent(server)
    assert any(part.get("type") == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,") for part in parts)
    store.launches["basalt"]["launch"]["settings"]["vision"] = "off"
    server2 = Server([({"content": "I cannot see it."}, "stop")])
    chat2 = ChatManager(store, cat, generation, uploads, opener=server2)
    record2 = upload(uploads, "square.png", PNG)
    follow(chat2.start(chat2.create()["id"], "What is this?", [{"file_id": record2["id"], "name": "square.png"}]))
    assert "picture reading is off" in str(sent(server2))
    assert not any(isinstance(part, dict) and part.get("type") == "image_url" for part in sent(server2))


def test_audio_video_and_missing_files_are_refused(setup):
    store, cat, generation, uploads = setup
    chat = ChatManager(store, cat, generation, uploads, opener=Server([]))
    conversation = chat.create()
    sound = upload(uploads, "talk.wav", b"RIFF\0\0\0\0WAVE" + b"\0" * 16)
    with pytest.raises(LifecycleError, match="pictures, PDFs and text files"):
        chat.start(conversation["id"], "Listen", [{"file_id": sound["id"], "name": "talk.wav"}])
    with pytest.raises(LifecycleError, match="no longer available"):
        chat.start(conversation["id"], "Read", [{"file_id": "0" * 32, "name": "gone.txt"}])


def test_a_library_meeting_and_a_decision_carry_their_words(setup, tmp_path):
    store, cat, generation, uploads = setup
    folder = tmp_path / "jobs" / "job-meeting"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("# Meeting notes\n- Ship Friday\n")
    (folder / "transcript.md").write_text("Anna: ship it Friday.\n")
    store.jobs["job-meeting"] = {"id": "job-meeting", "model_id": "notes", "status": "done", "inputs": {}, "launch": {},
                                 "outputs": [{"name": "transcript.md", "mime": "text/markdown"}, {"name": "notes.md", "mime": "text/markdown"}]}
    chat = ChatManager(store, cat, generation, uploads, opener=Server([({"content": "ok"}, "stop")]))
    job = store.jobs["job-meeting"]
    chat.catalog.runtimes["notes"] = type("R", (), {"kind": "meeting_notes", "name": "Meeting notes"})()
    text = chat._document_text(job)
    assert "Ship Friday" in text and "ship it Friday" in text and text.index("notes.md") < text.index("transcript.md")
    chat.catalog.runtimes["notes"] = type("R", (), {"kind": "yue2", "name": "Songs"})()
    assert chat._document_text(job) is None  # only meetings and decisions are read as text
