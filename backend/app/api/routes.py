"""HTTP API. Processing is asynchronous: create a meeting, then poll its status."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import PlainTextResponse

from ..schemas import JobStatus, MeetingDetail, MeetingList, MeetingSummary, TranscriptIn
from ..services.export import to_markdown
from ..services.pipeline import IN_FLIGHT
from ..services.transcript_parser import parse_transcript
from .deps import AppContainer, get_container

router = APIRouter(prefix="/api")

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".oga", ".opus", ".flac", ".aac", ".mov", ".mkv"}
)
TRANSCRIPT_EXTENSIONS = frozenset({".txt", ".vtt", ".srt"})
MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024
CHUNK = 1024 * 1024

Container = Annotated[AppContainer, Depends(get_container)]


def _safe_filename(name: str | None) -> str:
    base = Path(name or "upload").name.strip() or "upload"
    return base[:255]


def _today() -> dt.date:
    return dt.date.today()


@router.post("/meetings", status_code=status.HTTP_202_ACCEPTED, response_model=MeetingSummary)
async def upload_meeting(
    c: Container,
    file: Annotated[UploadFile, File(description="Meeting audio/video, or a .txt/.vtt/.srt transcript")],
    meeting_date: Annotated[dt.date | None, Form()] = None,
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> MeetingSummary:
    filename = _safe_filename(file.filename)
    ext = Path(filename).suffix.lower()
    date = meeting_date or _today()
    title = (title or "").strip() or None

    if ext in TRANSCRIPT_EXTENSIONS:
        raw = await file.read(MAX_TRANSCRIPT_BYTES + 1)
        if len(raw) > MAX_TRANSCRIPT_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "transcript file is too large")
        try:
            transcript = parse_transcript(raw.decode("utf-8-sig"))
        except UnicodeDecodeError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "transcript must be UTF-8 text") from e
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        meeting = c.repo.create(filename=filename, meeting_date=date, title=title, transcript=transcript)
        c.queue.submit(meeting.id)
        return meeting

    if ext not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(AUDIO_EXTENSIONS | TRANSCRIPT_EXTENSIONS))
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported file type {ext or '(none)'}; allowed: {allowed}",
        )

    limit = c.settings.max_upload_mb * 1024 * 1024
    c.settings.upload_dir.mkdir(parents=True, exist_ok=True)
    dest = c.settings.upload_dir / f"{uuid.uuid4()}{ext}"
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {c.settings.max_upload_mb} MB"
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "uploaded file is empty")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

    meeting = c.repo.create(filename=filename, meeting_date=date, title=title, audio_path=str(dest))
    c.queue.submit(meeting.id)
    return meeting


@router.post("/meetings/transcript", status_code=status.HTTP_202_ACCEPTED, response_model=MeetingSummary)
def submit_transcript(c: Container, body: TranscriptIn) -> MeetingSummary:
    try:
        transcript = parse_transcript(body.text)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    meeting = c.repo.create(
        filename="pasted-transcript.txt",
        meeting_date=body.meeting_date or _today(),
        title=(body.title or "").strip() or None,
        transcript=transcript,
    )
    c.queue.submit(meeting.id)
    return meeting


@router.get("/meetings", response_model=MeetingList)
def list_meetings(
    c: Container,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MeetingList:
    items, total = c.repo.list_meetings(limit=limit, offset=offset)
    return MeetingList(items=items, total=total)


def _get_or_404(c: AppContainer, meeting_id: str) -> MeetingDetail:
    meeting = c.repo.get(meeting_id)
    if meeting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "meeting not found")
    return meeting


@router.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def get_meeting(c: Container, meeting_id: str) -> MeetingDetail:
    return _get_or_404(c, meeting_id)


@router.get("/meetings/{meeting_id}/markdown", response_class=PlainTextResponse)
def export_markdown(c: Container, meeting_id: str) -> PlainTextResponse:
    meeting = _get_or_404(c, meeting_id)
    if meeting.notes is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "notes are not ready yet")
    return PlainTextResponse(
        to_markdown(meeting),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="meeting-{meeting.id[:8]}.md"'},
    )


@router.post(
    "/meetings/{meeting_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=MeetingSummary
)
def retry_meeting(c: Container, meeting_id: str) -> MeetingDetail:
    meeting = _get_or_404(c, meeting_id)
    if meeting.status != JobStatus.failed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"only failed meetings can be retried (status: {meeting.status})"
        )
    if meeting.transcript is None and not c.repo.get_audio_path(meeting_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "the audio for this meeting is gone; upload it again")
    c.repo.set_status(meeting_id, JobStatus.queued)
    c.queue.submit(meeting_id)
    return _get_or_404(c, meeting_id)


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(c: Container, meeting_id: str) -> None:
    meeting = _get_or_404(c, meeting_id)
    if meeting.status in IN_FLIGHT and c.queue.is_active(meeting_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "meeting is still processing")
    audio = c.repo.get_audio_path(meeting_id)
    c.repo.delete(meeting_id)
    if audio:
        Path(audio).unlink(missing_ok=True)


@router.get("/config")
def public_config(c: Container) -> dict[str, object]:
    """What the frontend needs to know: limits and whether we're in offline demo mode."""
    return {
        "max_upload_mb": c.settings.max_upload_mb,
        "audio_extensions": sorted(AUDIO_EXTENSIONS),
        "transcript_extensions": sorted(TRANSCRIPT_EXTENSIONS),
        "demo_mode": c.settings.extractor == "fake" or c.settings.transcriber == "fake",
    }
