from __future__ import annotations

import threading
from pathlib import Path

from app.db import MeetingRepository
from app.schemas import JobStatus, Transcript
from app.services.extraction import ExtractionError
from app.services.pipeline import JobQueue, MeetingProcessor
from app.services.transcription import DEMO_TRANSCRIPT, FakeTranscriber, TranscriptionError

from .conftest import MEETING_DATE, StubExtractor, short_transcript


def _audio(tmp_path: Path) -> Path:
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF....")
    return p


def test_processes_audio_end_to_end_and_deletes_audio(repo: MeetingRepository, tmp_path: Path) -> None:
    audio = _audio(tmp_path)
    m = repo.create(filename="a.wav", meeting_date=MEETING_DATE, audio_path=str(audio))
    extractor = StubExtractor()
    proc = MeetingProcessor(repo, FakeTranscriber(), extractor)

    assert proc.process(m.id) is JobStatus.completed

    done = repo.get(m.id)
    assert done is not None
    assert done.status is JobStatus.completed
    assert done.transcript == DEMO_TRANSCRIPT
    assert done.notes == extractor.notes
    assert done.title == "Mobile launch weekly sync"
    assert extractor.calls[0][1] == MEETING_DATE
    assert not audio.exists()
    assert repo.get_audio_path(m.id) is None


def test_user_title_is_not_overwritten(repo: MeetingRepository) -> None:
    m = repo.create(
        filename="t.txt", meeting_date=MEETING_DATE, title="My title", transcript=short_transcript()
    )
    MeetingProcessor(repo, FakeTranscriber(), StubExtractor()).process(m.id)
    done = repo.get(m.id)
    assert done is not None
    assert done.title == "My title"


def test_existing_transcript_skips_transcription(repo: MeetingRepository) -> None:
    m = repo.create(filename="t.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    transcriber = FakeTranscriber()
    MeetingProcessor(repo, transcriber, StubExtractor()).process(m.id)
    assert transcriber.calls == []


def test_keep_audio_when_configured(repo: MeetingRepository, tmp_path: Path) -> None:
    audio = _audio(tmp_path)
    m = repo.create(filename="a.wav", meeting_date=MEETING_DATE, audio_path=str(audio))
    MeetingProcessor(repo, FakeTranscriber(), StubExtractor(), delete_audio=False).process(m.id)
    assert audio.exists()


def test_transcription_failure_marks_failed_and_keeps_audio(repo: MeetingRepository, tmp_path: Path) -> None:
    class Broken:
        def transcribe(self, audio_path: Path) -> Transcript:
            raise TranscriptionError("no speech detected in the audio")

    audio = _audio(tmp_path)
    m = repo.create(filename="a.wav", meeting_date=MEETING_DATE, audio_path=str(audio))
    extractor = StubExtractor()
    assert MeetingProcessor(repo, Broken(), extractor).process(m.id) is JobStatus.failed
    failed = repo.get(m.id)
    assert failed is not None
    assert failed.status is JobStatus.failed
    assert failed.error == "no speech detected in the audio"
    assert extractor.calls == []
    assert audio.exists()  # kept so the user can retry


def test_extraction_failure_keeps_transcript(repo: MeetingRepository, tmp_path: Path) -> None:
    m = repo.create(filename="a.wav", meeting_date=MEETING_DATE, audio_path=str(_audio(tmp_path)))
    proc = MeetingProcessor(repo, FakeTranscriber(), StubExtractor(error=ExtractionError("rate limit")))
    assert proc.process(m.id) is JobStatus.failed
    failed = repo.get(m.id)
    assert failed is not None
    assert failed.transcript is not None
    assert failed.notes is None
    assert failed.error == "rate limit"


def test_unexpected_exception_is_hidden_from_user(repo: MeetingRepository) -> None:
    m = repo.create(filename="t.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    proc = MeetingProcessor(repo, FakeTranscriber(), StubExtractor(error=RuntimeError("secret detail")))
    assert proc.process(m.id) is JobStatus.failed
    failed = repo.get(m.id)
    assert failed is not None
    assert failed.error == "internal error while processing the meeting"


def test_missing_audio_and_transcript_fails(repo: MeetingRepository) -> None:
    m = repo.create(filename="a.wav", meeting_date=MEETING_DATE)
    assert MeetingProcessor(repo, FakeTranscriber(), StubExtractor()).process(m.id) is JobStatus.failed


def test_unknown_meeting_is_failed_not_raised(repo: MeetingRepository) -> None:
    assert MeetingProcessor(repo, FakeTranscriber(), StubExtractor()).process("nope") is JobStatus.failed


def test_queue_runs_jobs_and_dedupes(repo: MeetingRepository) -> None:
    gate = threading.Event()

    class Slow(StubExtractor):
        def extract(self, transcript, *, meeting_date):  # type: ignore[no-untyped-def]
            gate.wait(5)
            return super().extract(transcript, meeting_date=meeting_date)

    m = repo.create(filename="t.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    extractor = Slow()
    queue = JobQueue(MeetingProcessor(repo, FakeTranscriber(), extractor), workers=2)
    try:
        assert queue.submit(m.id) is True
        assert queue.submit(m.id) is False  # already running
        assert queue.is_active(m.id)
        gate.set()
        queue.join(timeout=5)
        assert len(extractor.calls) == 1
        done = repo.get(m.id)
        assert done is not None
        assert done.status is JobStatus.completed
        assert queue.submit(m.id) is True  # can be queued again once finished
        queue.join(timeout=5)
    finally:
        queue.shutdown()


def test_resume_requeues_in_flight_meetings(repo: MeetingRepository) -> None:
    stuck = repo.create(filename="t.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    repo.set_status(stuck.id, JobStatus.extracting)  # as if the process died mid-call
    finished = repo.create(filename="u.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    MeetingProcessor(repo, FakeTranscriber(), StubExtractor()).process(finished.id)

    extractor = StubExtractor()
    queue = JobQueue(MeetingProcessor(repo, FakeTranscriber(), extractor), workers=1)
    try:
        assert queue.resume() == 1
        queue.join(timeout=5)
    finally:
        queue.shutdown()
    done = repo.get(stuck.id)
    assert done is not None
    assert done.status is JobStatus.completed
    assert len(extractor.calls) == 1


def test_processes_meetings_concurrently(repo: MeetingRepository) -> None:
    barrier = threading.Barrier(3, timeout=5)

    class Rendezvous(StubExtractor):
        def extract(self, transcript, *, meeting_date):  # type: ignore[no-untyped-def]
            barrier.wait()  # only passes if 3 workers are inside extract() at once
            return super().extract(transcript, meeting_date=meeting_date)

    ids = [
        repo.create(filename=f"{i}.txt", meeting_date=MEETING_DATE, transcript=short_transcript()).id
        for i in range(3)
    ]
    queue = JobQueue(MeetingProcessor(repo, FakeTranscriber(), Rendezvous()), workers=3)
    try:
        for mid in ids:
            queue.submit(mid)
        queue.join(timeout=10)
    finally:
        queue.shutdown()
    for mid in ids:
        m = repo.get(mid)
        assert m is not None
        assert m.status is JobStatus.completed
