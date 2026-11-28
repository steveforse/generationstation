"""The saved voice library: named voice samples (a recording and the words it says) kept by the app on the host.

A voice lives under `<runtime_dir>/voices/` as one JSON record and one audio file. The sample comes from an upload
(so the same type and header checks apply); the library keeps its own copy, because uploads are removed after a day.
Using a voice is the page's job: it fetches the sample and attaches it to a clone request like any other sample.
"""
import json
import re
import shutil
import time
import uuid
from pathlib import Path

VOICE_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_NAME = 80
MAX_TEXT = 1000


class VoiceError(ValueError):
    """A request the library refuses: a bad name, a missing sample, a name already taken."""


class VoiceNotFound(LookupError):
    pass


class VoiceLibrary:
    def __init__(self, root: Path):
        self.root = Path(root) / "voices"

    def _clean(self, name, sample_text, keep_id=None):
        name = " ".join((name or "").split())
        if not name or len(name) > MAX_NAME:
            raise VoiceError(f"Give the voice a name of up to {MAX_NAME} characters.")
        text = " ".join((sample_text or "").split())
        if len(text) > MAX_TEXT:
            raise VoiceError(f"The words the sample says can be up to {MAX_TEXT} characters.")
        if any(voice["id"] != keep_id and voice["name"].casefold() == name.casefold() for voice in self.list()):
            raise VoiceError(f"A voice named {name!r} already exists.")
        return name, text

    def list(self) -> list[dict]:
        voices = []
        for meta in self.root.glob("*.json"):
            try:
                voices.append(json.loads(meta.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(voices, key=lambda voice: voice["name"].casefold())

    def get(self, voice_id) -> dict:
        if not isinstance(voice_id, str) or not VOICE_ID.match(voice_id):
            raise VoiceNotFound("That voice is not in the library.")
        try:
            return json.loads((self.root / f"{voice_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise VoiceNotFound("That voice is not in the library.") from exc

    def create(self, name: str, sample_text: str, upload: dict, source: Path) -> dict:
        """Save an uploaded audio file (its record and the path of its stored file) as a voice."""
        if not upload or upload.get("kind") != "audio":
            raise VoiceError("A voice needs an audio sample.")
        name, text = self._clean(name, sample_text)
        self.root.mkdir(parents=True, exist_ok=True)
        voice_id = uuid.uuid4().hex
        file = f"{voice_id}{Path(upload['file']).suffix}"
        shutil.copyfile(source, self.root / file)
        record = {"id": voice_id, "name": name, "sample_text": text, "file": file, "mime": upload["mime"], "bytes": upload["bytes"], "created": time.time()}
        (self.root / f"{voice_id}.json").write_text(json.dumps(record), encoding="utf-8")
        return record

    def update(self, voice_id: str, name: str, sample_text: str) -> dict:
        record = self.get(voice_id)
        record["name"], record["sample_text"] = self._clean(name, sample_text, keep_id=voice_id)
        (self.root / f"{voice_id}.json").write_text(json.dumps(record), encoding="utf-8")
        return record

    def delete(self, voice_id: str) -> None:
        record = self.get(voice_id)
        (self.root / record["file"]).unlink(missing_ok=True)
        (self.root / f"{voice_id}.json").unlink(missing_ok=True)

    def sample_path(self, voice_id: str) -> tuple[Path, str, str]:
        record = self.get(voice_id)
        path = self.root / record["file"]
        if not path.is_file():
            raise VoiceNotFound("That voice's sample is missing.")
        return path, record["mime"], f"{record['name']}{path.suffix}"
