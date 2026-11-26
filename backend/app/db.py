"""SQLite persistence for meetings via SQLAlchemy 2.0."""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import JSON, Date, DateTime, Engine, String, Text, create_engine, event, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .schemas import JobStatus, MeetingDetail, MeetingNotes, MeetingSummary, StoredNotes, Transcript


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    """SQLite drops tzinfo on the way back; every timestamp we store is UTC."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255))
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.queued.value, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meeting_date: Mapped[dt.date] = mapped_column(Date)
    transcript: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_summary(self) -> MeetingSummary:
        return MeetingSummary(
            id=self.id,
            filename=self.filename,
            status=JobStatus(self.status),
            title=self.title,
            meeting_date=self.meeting_date,
            created_at=_aware(self.created_at),
            updated_at=_aware(self.updated_at),
            error=self.error,
        )

    def to_detail(self) -> MeetingDetail:
        return MeetingDetail(
            **self.to_summary().model_dump(),
            transcript=Transcript.model_validate(self.transcript) if self.transcript else None,
            notes=StoredNotes.model_validate(self.notes) if self.notes else None,
        )


class Database:
    """Owns the engine and session factory."""

    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class NotesNotReadyError(LookupError):
    """The meeting exists but has no notes to edit yet."""


class MeetingRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._write_lock = threading.Lock()

    def create(
        self,
        *,
        filename: str,
        meeting_date: dt.date,
        audio_path: str | None = None,
        title: str | None = None,
        transcript: Transcript | None = None,
    ) -> MeetingSummary:
        with self.db.session() as s:
            m = Meeting(
                filename=filename,
                meeting_date=meeting_date,
                audio_path=audio_path,
                title=title,
                transcript=transcript.model_dump() if transcript else None,
            )
            s.add(m)
            s.flush()
            return m.to_summary()

    def get(self, meeting_id: str) -> MeetingDetail | None:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            return m.to_detail() if m else None

    def get_audio_path(self, meeting_id: str) -> str | None:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            return m.audio_path if m else None

    def list_meetings(self, *, limit: int = 50, offset: int = 0) -> tuple[list[MeetingSummary], int]:
        with self.db.session() as s:
            total = s.scalar(select(func.count()).select_from(Meeting)) or 0
            rows = s.scalars(
                select(Meeting).order_by(Meeting.created_at.desc()).limit(limit).offset(offset)
            ).all()
            return [r.to_summary() for r in rows], total

    def ids_with_status(self, *statuses: JobStatus) -> list[str]:
        with self.db.session() as s:
            return list(
                s.scalars(
                    select(Meeting.id)
                    .where(Meeting.status.in_([st.value for st in statuses]))
                    .order_by(Meeting.created_at)
                ).all()
            )

    def set_status(self, meeting_id: str, status: JobStatus, *, error: str | None = None) -> None:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            if m is None:
                raise KeyError(meeting_id)
            m.status = status.value
            m.error = error

    def save_transcript(self, meeting_id: str, transcript: Transcript) -> None:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            if m is None:
                raise KeyError(meeting_id)
            m.transcript = transcript.model_dump()

    def save_notes(self, meeting_id: str, notes: MeetingNotes) -> None:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            if m is None:
                raise KeyError(meeting_id)
            m.notes = StoredNotes.from_extracted(notes).model_dump(mode="json")
            m.title = m.title or notes.title
            m.status = JobStatus.completed.value
            m.error = None

    def update_notes[T](self, meeting_id: str, mutate: Callable[[StoredNotes], T]) -> T:
        """Read-modify-write the stored notes atomically and return ``mutate``'s result.

        ``mutate`` changes the notes in place. Raises ``KeyError`` if the meeting is gone
        and ``NotesNotReadyError`` if it has no notes yet. Writes go through a process-wide
        lock so two edits to the same meeting cannot overwrite each other.
        """
        with self._write_lock, self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            if m is None:
                raise KeyError(meeting_id)
            if m.notes is None:
                raise NotesNotReadyError(meeting_id)
            notes = StoredNotes.model_validate(m.notes)
            result = mutate(notes)
            # Re-validate so a mutation can never persist something the API would reject.
            m.notes = StoredNotes.model_validate(notes.model_dump()).model_dump(mode="json")
            return result

    def clear_audio_path(self, meeting_id: str) -> None:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            if m is not None:
                m.audio_path = None

    def delete(self, meeting_id: str) -> bool:
        with self.db.session() as s:
            m = s.get(Meeting, meeting_id)
            if m is None:
                return False
            s.delete(m)
            return True
