"""Files people attach to a generation request (reference pictures, videos, audio).

An upload is kept under `<runtime_dir>/uploads/` until a job uses it; the job then gets its own copy in
its output folder, so a result keeps its references and they go when it is deleted. Unused uploads are
removed after a day. The type is decided by the file's first bytes as well as its name, so a renamed
file of another kind is refused.
"""
import json
import re
import shutil
import time
import uuid
from pathlib import Path

KINDS = {
    "image": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"},
    "video": {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/mp4"},
    "audio": {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg"},
    # Files for the chat to read: a PDF (its text is extracted), and text or code (.txt and .md count as transcripts below).
    "document": {".pdf": "application/pdf", ".csv": "text/csv", ".json": "application/json", ".log": "text/plain",
                 ".yaml": "text/yaml", ".yml": "text/yaml", ".toml": "text/plain", ".xml": "application/xml",
                 ".html": "text/html", ".htm": "text/html", ".css": "text/css", ".sql": "text/plain", ".sh": "text/plain",
                 ".py": "text/x-python", ".js": "text/javascript", ".ts": "text/plain", ".tsx": "text/plain",
                 ".jsx": "text/plain", ".java": "text/plain", ".c": "text/plain", ".h": "text/plain", ".cpp": "text/plain",
                 ".rs": "text/plain", ".go": "text/plain", ".rb": "text/plain", ".ini": "text/plain"},
    # A transcript someone already has (a Zoom .vtt or .txt, an .srt, notes): text, UTF-8.
    "transcript": {".txt": "text/plain", ".md": "text/markdown", ".vtt": "text/vtt", ".srt": "application/x-subrip"},
}
# Video and audio allow an hour-long meeting recording (a Zoom MP4 of an hour is often 300-800 MB).
MAX_BYTES = {"image": 25 * 1024**2, "video": 2048 * 1024**2, "audio": 600 * 1024**2, "transcript": 20 * 1024**2, "document": 30 * 1024**2}
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
KEEP_SECONDS = 24 * 3600


class UploadError(ValueError):
    pass


def kind_of(name: str):
    suffix = Path(name).suffix.lower()
    for kind, types in KINDS.items():
        if suffix in types:
            return kind, suffix, types[suffix]
    return None, suffix, None


def _looks_like(suffix: str, head: bytes) -> bool:
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if suffix == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if suffix in {".mp4", ".mov", ".m4v", ".m4a"}:
        return head[4:8] == b"ftyp"
    if suffix == ".webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if suffix == ".wav":
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    if suffix == ".mp3":
        return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if suffix == ".flac":
        return head.startswith(b"fLaC")
    if suffix == ".ogg":
        return head.startswith(b"OggS")
    if suffix == ".pdf":
        return head.startswith(b"%PDF-")
    if suffix in KINDS["transcript"] or suffix in KINDS["document"]:
        return _looks_like_text(head)
    return False


def _looks_like_text(head: bytes) -> bool:
    """UTF-8 text (an optional byte-order mark is fine): no NUL bytes, and no bad bytes before a cut-off last character."""
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return exc.start >= len(head) - 3 and exc.reason == "unexpected end of data"
    return True


def safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-.")[:60] or "file"
    return stem + Path(name).suffix.lower()


class UploadStore:
    def __init__(self, root: Path):
        self.root = Path(root) / "uploads"

    async def save_stream(self, name: str, stream) -> dict:
        """Store an upload from an async stream of byte chunks (a request body). Returns its record."""
        chunks = []
        size = 0
        kind, _, _ = kind_of(name or "")
        limit = MAX_BYTES.get(kind, 0)
        async for chunk in stream:
            size += len(chunk)
            if kind and size > limit:
                raise UploadError(f"That {kind} is too large (at most {limit // 1024**2} MB).")
            chunks.append(chunk)
            if kind is None:
                break  # refused below without reading the rest
        return self.save(name, chunks)

    def save(self, name: str, chunks) -> dict:
        """Store an upload from an iterable of byte chunks. Returns its record."""
        kind, suffix, mime = kind_of(name or "")
        if kind is None:
            accepted = ", ".join(sorted(s for types in KINDS.values() for s in types))
            raise UploadError(f"That type of file is not accepted. Use one of: {accepted}.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.prune()
        upload_id = uuid.uuid4().hex
        path = self.root / f"{upload_id}{suffix}"
        size, head = 0, b""
        try:
            with path.open("wb") as out:
                for chunk in chunks:
                    size += len(chunk)
                    if size > MAX_BYTES[kind]:
                        raise UploadError(f"That {kind} is too large (at most {MAX_BYTES[kind] // 1024**2} MB).")
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    out.write(chunk)
            if size == 0 or not _looks_like(suffix, head):
                raise UploadError(f"That file is not a valid {suffix[1:].upper()} {kind}.")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        record = {"id": upload_id, "name": safe_name(name), "kind": kind, "mime": mime, "bytes": size,
                  "file": path.name}
        (self.root / f"{upload_id}.json").write_text(json.dumps(record), encoding="utf-8")
        return {key: record[key] for key in ("id", "name", "kind", "mime", "bytes")}

    def get(self, upload_id) -> dict | None:
        if not isinstance(upload_id, str) or not UPLOAD_ID.match(upload_id):
            return None
        meta = self.root / f"{upload_id}.json"
        try:
            record = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return record if (self.root / record["file"]).is_file() else None

    def copy_to(self, record: dict, folder: Path, index: int) -> str:
        """Copy an upload into a job's folder; returns its name there."""
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{index:02d}-{record['name']}"
        shutil.copyfile(self.root / record["file"], folder / name)
        return name

    def prune(self):
        cutoff = time.time() - KEEP_SECONDS
        for path in self.root.glob("*"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
