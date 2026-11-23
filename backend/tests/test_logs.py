"""Model server logs: listed with their start's outcome; only log files can be read."""
import pytest

from generationstation.logs import LogNotFound, LogStore

OP = "12345678-1234-1234-1234-123456789abc"


class Store:
    def get_operation(self, operation_id):
        if operation_id == OP:
            return {"model_id": "yue2", "action": "load", "status": "failed", "error_code": "WORKER_EXITED",
                    "error_message": "The worker exited during the load.", "created_at": "2026-11-22T10:00:00+00:00"}
        return None


def make(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / f"yue2-{OP}.log").write_bytes("".join(f"line {i}\r\n" for i in range(1, 1201)).encode())
    (logs / "access.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    return LogStore(tmp_path, Store())


def test_logs_are_listed_with_their_start(tmp_path):
    listed = make(tmp_path).list()["logs"]
    assert [row["name"] for row in listed] == [f"yue2-{OP}.log"]  # access.jsonl is not a model log
    row = listed[0]
    assert (row["model_id"], row["action"], row["status"], row["error_code"]) == ("yue2", "load", "failed", "WORKER_EXITED")


def test_reading_returns_the_last_lines(tmp_path):
    store = make(tmp_path)
    text = store.read(f"yue2-{OP}.log", 3)
    assert text["lines"] == ["line 1198", "line 1199", "line 1200"] and text["truncated"] is True
    assert len(store.read(f"yue2-{OP}.log", 5000)["lines"]) == 1200


@pytest.mark.parametrize("name", ["access.jsonl", "../secret.txt", "..\\secret.txt", f"yue2-{OP}.log/../../secret.txt",
                                  f"other-{OP}.log", ""])
def test_nothing_else_can_be_read(tmp_path, name):
    with pytest.raises(LogNotFound):
        make(tmp_path).read(name)
