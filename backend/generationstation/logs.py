"""Model server logs: one file per start (`runtime/logs/<kind>-<operation>.log`), listed with that start's outcome.

Only files whose names match that pattern are listed or read, so a request cannot name any other file.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

NAME = re.compile(r"^([a-z0-9_]+)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.log$")
MAX_LINES = 5000
MAX_BYTES = 4 * 1024 * 1024  # read at most this much from the end of a file


class LogNotFound(LookupError):
    pass


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class LogStore:
    def __init__(self, runtime_dir: Path, store):
        self.root = Path(runtime_dir) / "logs"
        self.store = store

    def _files(self):
        if not self.root.is_dir():
            return []
        return [path for path in self.root.iterdir() if path.is_file() and NAME.match(path.name)]

    def list(self, limit=200):
        rows = []
        for path in sorted(self._files(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            kind, operation_id = NAME.match(path.name).groups()
            stat = path.stat()
            operation = self.store.get_operation(operation_id) if hasattr(self.store, "get_operation") else None
            rows.append({
                "name": path.name, "bytes": stat.st_size, "kind": kind,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "operation_id": operation_id,
                "model_id": (operation or {}).get("model_id"), "action": (operation or {}).get("action"),
                "status": (operation or {}).get("status"), "error_code": (operation or {}).get("error_code"),
                "error_message": (operation or {}).get("error_message"),
                "started_at": _iso((operation or {}).get("created_at")),
            })
        return {"logs": rows}

    def read(self, name: str, lines: int = 500):
        match = NAME.match(name or "")
        path = (self.root / name).resolve() if match else None
        if path is None or path.parent != self.root.resolve() or not path.is_file():
            raise LogNotFound(name)
        lines = max(1, min(int(lines), MAX_LINES))
        size = path.stat().st_size
        with path.open("rb") as handle:
            start = max(0, size - MAX_BYTES)
            handle.seek(start)
            data = handle.read()
        text = re.sub(r"\r*\n|\r", "\n", data.decode("utf-8", errors="replace"))  # CRLF, doubled CR (Windows text mode) or bare CR
        all_lines = text.split("\n")
        if start > 0:
            all_lines = all_lines[1:]  # the first line was cut by the byte limit
        if all_lines and all_lines[-1] == "":
            all_lines.pop()
        shown = all_lines[-lines:]
        return {"name": name, "bytes": size, "lines": shown,
                "truncated": start > 0 or len(all_lines) > len(shown)}
