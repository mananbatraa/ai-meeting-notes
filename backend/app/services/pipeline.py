"""Background processing: audio -> transcript -> notes, persisted at every step."""

from __future__ import annotations

import contextlib
import functools
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from ..db import MeetingRepository
from ..schemas import JobStatus
from .extraction import ExtractionError, NotesExtractor
from .transcription import Transcriber, TranscriptionError

log = logging.getLogger(__name__)

IN_FLIGHT = (JobStatus.queued, JobStatus.transcribing, JobStatus.extracting)


class MeetingProcessor:
    """Runs one meeting through the pipeline. Synchronous; safe to call from threads."""

    def __init__(
        self,
        repo: MeetingRepository,
        transcriber: Transcriber,
        extractor: NotesExtractor,
        *,
        delete_audio: bool = True,
    ) -> None:
        self.repo = repo
        self.transcriber = transcriber
        self.extractor = extractor
        self.delete_audio = delete_audio

    def process(self, meeting_id: str) -> JobStatus:
        meeting = self.repo.get(meeting_id)
        if meeting is None:
            log.warning("meeting %s vanished before processing", meeting_id)
            return JobStatus.failed
        try:
            transcript = meeting.transcript
            if transcript is None:
                audio = self.repo.get_audio_path(meeting_id)
                if not audio:
                    raise TranscriptionError("no audio or transcript to process")
                self.repo.set_status(meeting_id, JobStatus.transcribing)
                transcript = self.transcriber.transcribe(Path(audio))
                self.repo.save_transcript(meeting_id, transcript)

            self.repo.set_status(meeting_id, JobStatus.extracting)
            notes = self.extractor.extract(transcript, meeting_date=meeting.meeting_date)
            self.repo.save_notes(meeting_id, notes)
        except (TranscriptionError, ExtractionError) as e:
            log.warning("meeting %s failed: %s", meeting_id, e)
            self._fail(meeting_id, str(e))
            return JobStatus.failed
        except Exception:
            log.exception("meeting %s crashed", meeting_id)
            self._fail(meeting_id, "internal error while processing the meeting")
            return JobStatus.failed

        if self.delete_audio:
            self._remove_audio(meeting_id)
        return JobStatus.completed

    def _fail(self, meeting_id: str, message: str) -> None:
        with contextlib.suppress(KeyError):  # deleted while processing
            self.repo.set_status(meeting_id, JobStatus.failed, error=message)

    def _remove_audio(self, meeting_id: str) -> None:
        audio = self.repo.get_audio_path(meeting_id)
        if audio:
            Path(audio).unlink(missing_ok=True)
            self.repo.clear_audio_path(meeting_id)


class JobQueue:
    """Bounded thread pool. Whisper and the Claude call are blocking, so threads fit.

    State lives in the database, not in the queue, so on startup ``resume()`` re-queues
    anything a previous process left in flight.
    """

    def __init__(self, processor: MeetingProcessor, *, workers: int = 2) -> None:
        self.processor = processor
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="meeting")
        self._pending: dict[str, Future[JobStatus]] = {}
        self._lock = threading.Lock()

    def submit(self, meeting_id: str) -> bool:
        """Queue a meeting. Returns False if it is already queued or running."""
        with self._lock:
            fut = self._pending.get(meeting_id)
            if fut is not None and not fut.done():
                return False
            fut = self._pool.submit(self.processor.process, meeting_id)
            self._pending[meeting_id] = fut
            fut.add_done_callback(functools.partial(self._forget, meeting_id))
            return True

    def _forget(self, meeting_id: str, fut: Future[JobStatus]) -> None:
        with self._lock:
            if self._pending.get(meeting_id) is fut:
                del self._pending[meeting_id]

    def is_active(self, meeting_id: str) -> bool:
        with self._lock:
            return meeting_id in self._pending

    def resume(self) -> int:
        ids = self.processor.repo.ids_with_status(*IN_FLIGHT)
        for mid in ids:
            self.processor.repo.set_status(mid, JobStatus.queued)
            self.submit(mid)
        return len(ids)

    def join(self, timeout: float | None = None) -> None:
        """Wait for everything currently queued (used by tests and shutdown)."""
        with self._lock:
            futures = list(self._pending.values())
        for f in futures:
            f.result(timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)
