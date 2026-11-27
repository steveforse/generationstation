"""Files attached to a chat message: pictures, PDFs and text or code.

A person's upload (uploads.py) is copied into `<runtime_dir>/chat-files/` when the message is sent, so it stays with the
conversation after the upload's day is up. A PDF or text file is read to text at that moment (the model is given the text),
so a file that cannot be read is refused up front rather than failing the answer. Pictures are kept as they are.
"""
import json
import re
import shutil
from pathlib import Path

MAX_DOC_CHARS = 120_000   # about 30,000 tokens: what one attached file may add to a request
MAX_PDF_PAGES = 400
MAX_PICTURE_BYTES = 12 * 1024**2  # a larger picture takes the chat model minutes to read
ATTACHABLE = {"image", "document", "transcript"}  # upload kinds the chat takes (not audio or video)
FILE_ID = re.compile(r"^[0-9a-f]{32}$")


class ChatFileError(ValueError):
    pass


def _cut(text: str) -> str:
    if len(text) <= MAX_DOC_CHARS:
        return text
    return text[:MAX_DOC_CHARS] + f"\n\n[Cut here: the file has {len(text):,} characters and the first {MAX_DOC_CHARS:,} are shown.]"


def read_text(path: Path, suffix: str) -> str:
    """The readable text of a PDF or text file, cut to MAX_DOC_CHARS."""
    if suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError

        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ChatFileError("That PDF is password-protected.")
            pages, total = [], 0
            for number, page in enumerate(reader.pages[:MAX_PDF_PAGES], 1):
                text = (page.extract_text() or "").strip()
                if text:
                    pages.append(f"[Page {number}]\n{text}")
                    total += len(text)
                if total > MAX_DOC_CHARS:
                    break
        except ChatFileError:
            raise
        except (PyPdfError, ValueError, OSError, KeyError, TypeError) as exc:
            raise ChatFileError("That PDF could not be read.") from exc
        text = "\n\n".join(pages)
        if not text:
            raise ChatFileError("That PDF has no text to read (a scan, perhaps). Attach its pages as pictures instead.")
        return _cut(text)
    text = path.read_bytes().decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise ChatFileError("That file is empty.")
    return _cut(text)


class ChatFiles:
    def __init__(self, uploads):
        self.uploads = uploads
        self.root = Path(uploads.root).parent / "chat-files"

    def attach(self, upload_id) -> dict:
        """Keep an upload with the conversation; returns the attachment record the message stores."""
        record = self.uploads.get(upload_id)
        if record is None:
            raise ChatFileError("An attached file is no longer available. Add it again.")
        kind = record["kind"]
        if kind not in ATTACHABLE:
            raise ChatFileError("The chat reads pictures, PDFs and text files. Use the model pages for audio and video.")
        source = Path(self.uploads.root) / record["file"]
        suffix = source.suffix.lower()
        if kind == "image" and record["bytes"] > MAX_PICTURE_BYTES:
            raise ChatFileError(f"That picture is too large for the chat (at most {MAX_PICTURE_BYTES // 1024**2} MB).")
        text = None if kind == "image" else read_text(source, suffix)
        self.root.mkdir(parents=True, exist_ok=True)
        stored = self.root / f"{record['id']}{suffix}"
        shutil.copyfile(source, stored)
        if text is not None:
            (self.root / f"{record['id']}.txt").write_text(text, encoding="utf-8")
        attachment = {"file_id": record["id"], "name": record["name"], "mime": record["mime"], "kind": kind, "bytes": record["bytes"]}
        (self.root / f"{record['id']}.json").write_text(json.dumps({**attachment, "file": stored.name}), encoding="utf-8")
        return attachment

    def record(self, file_id):
        if not isinstance(file_id, str) or not FILE_ID.match(file_id):
            return None
        try:
            record = json.loads((self.root / f"{file_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return record if (self.root / record["file"]).is_file() else None

    def path(self, file_id):
        record = self.record(file_id)
        return (self.root / record["file"], record["mime"], record["name"]) if record else None

    def text(self, file_id):
        try:
            return (self.root / f"{file_id}.txt").read_text(encoding="utf-8") if FILE_ID.match(file_id) else None
        except OSError:
            return None

    def delete(self, file_id):
        if not isinstance(file_id, str) or not FILE_ID.match(file_id):
            return
        for path in self.root.glob(f"{file_id}.*"):
            path.unlink(missing_ok=True)
