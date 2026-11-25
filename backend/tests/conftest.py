from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database, MeetingRepository
from app.main import create_app
from app.schemas import ActionItem, Decision, MeetingNotes, Priority, Segment, Transcript
from app.services.transcription import DEMO_TRANSCRIPT, FakeTranscriber

MEETING_DATE = dt.date(2026, 11, 25)  # a Wednesday


def sample_notes() -> MeetingNotes:
    return MeetingNotes(
        title="Mobile launch weekly sync",
        summary="The team reviewed launch readiness and moved the public launch to the 10th.",
        key_points=["iOS passed review", "Android blocked on payments SDK"],
        decisions=[Decision(decision="Move the public launch to the 10th", timestamp_s=40.0)],
        action_items=[
            ActionItem(
                task="Finish the payments SDK upgrade",
                owner="Sam",
                due_date=dt.date(2026, 11, 27),
                priority=Priority.high,
                timestamp_s=15.0,
            ),
            ActionItem(task="Update the launch brief", owner="Lee", due_date=MEETING_DATE),
        ],
        open_questions=["Do we still need the agency press kit?"],
        participants=["Priya", "Sam", "Lee"],
    )


class StubExtractor:
    """Returns fixed notes and records what it was given."""

    def __init__(self, notes: MeetingNotes | None = None, error: Exception | None = None) -> None:
        self.notes = notes or sample_notes()
        self.error = error
        self.calls: list[tuple[Transcript, dt.date]] = []

    def extract(self, transcript: Transcript, *, meeting_date: dt.date) -> MeetingNotes:
        self.calls.append((transcript, meeting_date))
        if self.error:
            raise self.error
        return self.notes


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        max_upload_mb=1,
        transcriber="fake",
        extractor="fake",
        worker_concurrency=2,
    )


@pytest.fixture
def repo(settings: Settings) -> MeetingRepository:
    db = Database(settings.database_url)
    db.create_all()
    return MeetingRepository(db)


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber(DEMO_TRANSCRIPT)


@pytest.fixture
def extractor() -> StubExtractor:
    return StubExtractor()


@pytest.fixture
def client(
    settings: Settings, transcriber: FakeTranscriber, extractor: StubExtractor
) -> Iterator[TestClient]:
    app = create_app(settings, transcriber=transcriber, extractor=extractor)
    with TestClient(app) as c:
        yield c


def wait_done(client: TestClient) -> None:
    client.app.state.container.queue.join(timeout=10)  # type: ignore[attr-defined]


def short_transcript() -> Transcript:
    return Transcript(
        duration_s=30.0,
        segments=[
            Segment(start=0, end=10, speaker="Ana", text="Ben, please send the report by Friday."),
            Segment(start=10, end=30, speaker="Ben", text="Sure, I will."),
        ],
    )
