from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.extraction import ExtractionError
from app.services.transcription import FakeTranscriber

from .conftest import StubExtractor, wait_done

VTT = b"WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n<v Ana>Ben, send the report by Friday.\n"


def upload(client: TestClient, name: str = "standup.mp3", data: bytes = b"ID3fakeaudio", **form: str):  # type: ignore[no-untyped-def]
    return client.post("/api/meetings", files={"file": (name, data, "application/octet-stream")}, data=form)


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_upload_audio_is_processed(client: TestClient, settings: Settings, extractor: StubExtractor) -> None:
    r = upload(client, meeting_date="2026-11-25", title="Launch sync")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["filename"] == "standup.mp3"
    wait_done(client)

    m = client.get(f"/api/meetings/{body['id']}").json()
    assert m["status"] == "completed"
    assert m["title"] == "Launch sync"
    assert m["meeting_date"] == "2026-11-25"
    first = m["notes"]["action_items"][0]
    assert len(first.pop("id")) == 12
    assert first == {
        "done": False,
        "edited": False,
        "task": "Finish the payments SDK upgrade",
        "owner": "Sam",
        "due_date": "2026-11-27",
        "priority": "high",
        "timestamp_s": 15.0,
    }
    assert len(m["transcript"]["segments"]) == 10
    assert extractor.calls[0][1] == dt.date(2026, 11, 25)
    assert list(settings.upload_dir.iterdir()) == []  # audio removed after success


def test_timestamps_are_timezone_aware_after_reload(client: TestClient) -> None:
    mid = upload(client).json()["id"]
    wait_done(client)
    for m in (client.get(f"/api/meetings/{mid}").json(), client.get("/api/meetings").json()["items"][0]):
        assert m["created_at"].endswith("Z") or m["created_at"].endswith("+00:00")


def test_meeting_date_defaults_to_today(client: TestClient) -> None:
    body = upload(client).json()
    assert body["meeting_date"] == dt.date.today().isoformat()


def test_upload_strips_directories_from_filename(client: TestClient) -> None:
    assert upload(client, name="../../etc/passwd.wav").json()["filename"] == "passwd.wav"


def test_upload_transcript_file_skips_transcription(client: TestClient, transcriber: FakeTranscriber) -> None:
    r = upload(client, name="call.vtt", data=VTT)
    assert r.status_code == 202
    wait_done(client)
    m = client.get(f"/api/meetings/{r.json()['id']}").json()
    assert m["status"] == "completed"
    assert m["transcript"]["segments"][0]["speaker"] == "Ana"
    assert transcriber.calls == []


def test_paste_transcript(client: TestClient) -> None:
    r = client.post(
        "/api/meetings/transcript",
        json={"text": "Ana: Ben, send the report.\nBen: Sure.", "title": "1:1", "meeting_date": "2026-11-20"},
    )
    assert r.status_code == 202
    assert r.json()["filename"] == "pasted-transcript.txt"
    wait_done(client)
    m = client.get(f"/api/meetings/{r.json()['id']}").json()
    assert m["status"] == "completed"
    assert m["title"] == "1:1"


@pytest.mark.parametrize(
    ("payload", "code"),
    [({"text": "   \n"}, 422), ({"text": ""}, 422), ({"text": "hi", "extra": 1}, 422)],
)
def test_paste_transcript_validation(client: TestClient, payload: dict[str, object], code: int) -> None:
    assert client.post("/api/meetings/transcript", json=payload).status_code == code


def test_rejects_unsupported_extension(client: TestClient) -> None:
    r = upload(client, name="malware.exe")
    assert r.status_code == 415
    assert ".mp3" in r.json()["detail"]


def test_rejects_oversized_upload_and_cleans_up(client: TestClient, settings: Settings) -> None:
    r = upload(client, data=b"x" * (settings.max_upload_mb * 1024 * 1024 + 1))
    assert r.status_code == 413
    assert list(settings.upload_dir.iterdir()) == []
    assert client.get("/api/meetings").json()["total"] == 0


def test_rejects_empty_upload(client: TestClient) -> None:
    assert upload(client, data=b"").status_code == 422


def test_rejects_non_utf8_transcript(client: TestClient) -> None:
    assert upload(client, name="t.txt", data=b"\xff\xfe\x00bad").status_code == 422


def test_rejects_empty_transcript_file(client: TestClient) -> None:
    assert upload(client, name="t.srt", data=b"\n\n").status_code == 422


def test_rejects_bad_meeting_date(client: TestClient) -> None:
    assert upload(client, meeting_date="yesterday").status_code == 422


def test_list_is_newest_first_and_paginated(client: TestClient) -> None:
    ids = [upload(client, name=f"{i}.wav").json()["id"] for i in range(3)]
    wait_done(client)
    page = client.get("/api/meetings", params={"limit": 2}).json()
    assert page["total"] == 3
    assert [m["id"] for m in page["items"]] == ids[::-1][:2]
    rest = client.get("/api/meetings", params={"limit": 2, "offset": 2}).json()
    assert [m["id"] for m in rest["items"]] == [ids[0]]
    assert "notes" not in page["items"][0]
    assert client.get("/api/meetings", params={"limit": 1000}).status_code == 422


def test_unknown_meeting_404(client: TestClient) -> None:
    assert client.get("/api/meetings/nope").status_code == 404
    assert client.get("/api/meetings/nope/markdown").status_code == 404
    assert client.post("/api/meetings/nope/retry").status_code == 404
    assert client.delete("/api/meetings/nope").status_code == 404


def test_markdown_export(client: TestClient) -> None:
    mid = upload(client, meeting_date="2026-11-25").json()["id"]
    wait_done(client)
    r = client.get(f"/api/meetings/{mid}/markdown")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"]
    assert "| Finish the payments SDK upgrade | Sam | 2026-11-27 | high |" in r.text


def _failing_client(settings: Settings, extractor: StubExtractor) -> TestClient:
    return TestClient(create_app(settings, transcriber=FakeTranscriber(), extractor=extractor))


def test_failed_meeting_can_be_retried(settings: Settings) -> None:
    extractor = StubExtractor(error=ExtractionError("Claude API rate limit reached", retryable=True))
    with _failing_client(settings, extractor) as client:
        mid = upload(client).json()["id"]
        wait_done(client)
        failed = client.get(f"/api/meetings/{mid}").json()
        assert failed["status"] == "failed"
        assert failed["error"] == "Claude API rate limit reached"
        assert client.get(f"/api/meetings/{mid}/markdown").status_code == 409

        extractor.error = None
        r = client.post(f"/api/meetings/{mid}/retry")
        assert r.status_code == 202
        wait_done(client)
        done = client.get(f"/api/meetings/{mid}").json()
        assert done["status"] == "completed"
        assert done["error"] is None
        assert client.post(f"/api/meetings/{mid}/retry").status_code == 409  # not failed any more


def test_delete_meeting_removes_audio(settings: Settings) -> None:
    extractor = StubExtractor(error=ExtractionError("nope"))
    with _failing_client(settings, extractor) as client:
        mid = upload(client).json()["id"]
        wait_done(client)
        assert len(list(settings.upload_dir.iterdir())) == 1  # kept for retry
        assert client.delete(f"/api/meetings/{mid}").status_code == 204
        assert list(settings.upload_dir.iterdir()) == []
        assert client.get(f"/api/meetings/{mid}").status_code == 404


def test_restart_resumes_unfinished_work(settings: Settings, tmp_path: Path) -> None:
    from app.db import Database, MeetingRepository
    from app.schemas import JobStatus

    from .conftest import short_transcript

    db = Database(settings.database_url)
    db.create_all()
    repo = MeetingRepository(db)
    m = repo.create(filename="t.txt", meeting_date=dt.date(2026, 11, 25), transcript=short_transcript())
    repo.set_status(m.id, JobStatus.extracting)

    with TestClient(create_app(settings, transcriber=FakeTranscriber(), extractor=StubExtractor())) as client:
        wait_done(client)
        assert client.get(f"/api/meetings/{m.id}").json()["status"] == "completed"


def test_public_config(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert cfg["max_upload_mb"] == 1
    assert ".wav" in cfg["audio_extensions"]
    assert ".vtt" in cfg["transcript_extensions"]
    assert cfg["demo_mode"] is True


def test_cors_allows_frontend_origin(client: TestClient) -> None:
    r = client.options(
        "/api/meetings",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
