"""The saved voice library: save an uploaded sample under a name, list, rename, fetch the sample, delete."""
import struct

import pytest
from fastapi.testclient import TestClient

from generationstation.app import create_app
from tests.test_app import TOKEN, FakeMonitor, FakeStore, settings


def wav(seconds=0.1, rate=8000) -> bytes:
    count = int(seconds * rate)
    data = b"\x00\x00" * count
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def client(tmp_path):
    app = create_app(settings=settings(runtime_dir=tmp_path), store=FakeStore(), monitor=FakeMonitor())
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


def upload(client, name="sample.wav", data=None):
    response = client.post("/api/uploads", params={"name": name}, content=data or wav())
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_voice_is_saved_listed_renamed_fetched_and_deleted(client):
    assert client.get("/api/voices").json() == {"voices": []}
    created = client.post("/api/voices", json={"name": "  Anna  warm ", "sample_text": "Come in.\n  Sit down.", "upload_id": upload(client)})
    assert created.status_code == 201
    voice = created.json()
    assert voice["name"] == "Anna warm" and voice["sample_text"] == "Come in. Sit down." and voice["mime"] == "audio/wav"
    assert client.get("/api/voices").json()["voices"] == [voice]
    sample = client.get(f"/api/voices/{voice['id']}/sample")
    assert sample.status_code == 200 and sample.content[:4] == b"RIFF"
    renamed = client.put(f"/api/voices/{voice['id']}", json={"name": "Anna", "sample_text": "Come in."})
    assert renamed.json()["name"] == "Anna" and renamed.json()["sample_text"] == "Come in."
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 200
    assert client.get("/api/voices").json() == {"voices": []}
    assert client.get(f"/api/voices/{voice['id']}/sample").status_code == 404
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 404


def test_the_library_keeps_its_own_copy_so_a_pruned_upload_does_not_lose_the_voice(client, tmp_path):
    upload_id = upload(client)
    voice = client.post("/api/voices", json={"name": "Kept", "upload_id": upload_id}).json()
    for path in (tmp_path / "uploads").glob("*"):
        path.unlink()
    assert client.get(f"/api/voices/{voice['id']}/sample").status_code == 200


def test_names_must_be_present_and_unique_and_the_sample_must_be_audio(client):
    first = upload(client)
    assert client.post("/api/voices", json={"name": " ", "upload_id": first}).status_code == 422
    assert client.post("/api/voices", json={"name": "Anna", "upload_id": first}).status_code == 201
    assert client.post("/api/voices", json={"name": "ANNA", "upload_id": first}).status_code == 422  # names differ by more than case
    assert client.post("/api/voices", json={"name": "Missing", "upload_id": "0" * 32}).status_code == 422
    picture = client.post("/api/uploads", params={"name": "a.png"}, content=b"\x89PNG\r\n\x1a\n" + b"0" * 20).json()["id"]
    assert client.post("/api/voices", json={"name": "Picture", "upload_id": picture}).status_code == 422
    other = client.post("/api/voices", json={"name": "Ben", "upload_id": first}).json()
    assert client.put(f"/api/voices/{other['id']}", json={"name": "anna", "sample_text": ""}).status_code == 422
    assert client.put(f"/api/voices/{other['id']}", json={"name": "Ben", "sample_text": "x" * 1001}).status_code == 422
    assert client.put("/api/voices/" + "1" * 32, json={"name": "Z", "sample_text": ""}).status_code == 404
    assert client.get("/api/voices/..%2f..%2fetc/sample").status_code == 404
