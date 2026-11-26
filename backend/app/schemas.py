"""Pydantic models: the notes contract returned by the LLM and the API shapes."""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, description="What was decided, as one sentence.")
    context: str | None = Field(default=None, description="Why it was decided, if stated in the meeting.")
    timestamp_s: float | None = Field(
        default=None, ge=0, description="Seconds into the meeting where it was decided."
    )


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, description="The concrete task, starting with a verb.")
    owner: str | None = Field(
        default=None, description="Person responsible, exactly as named in the meeting; null if unassigned."
    )
    due_date: dt.date | None = Field(
        default=None, description="ISO date (YYYY-MM-DD) the task is due; null if none was given."
    )
    priority: Priority = Priority.medium
    timestamp_s: float | None = Field(
        default=None, ge=0, description="Seconds into the meeting where it was assigned."
    )

    @field_validator("owner")
    @classmethod
    def _blank_owner_is_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class MeetingNotes(BaseModel):
    """Structured notes. This model is also the JSON schema sent to Claude."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200, description="Short descriptive meeting title.")
    summary: str = Field(min_length=1, description="3-6 sentence summary of the meeting.")
    key_points: list[str] = Field(default_factory=list, description="Main discussion points.")
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list, description="Questions raised but not resolved.")
    participants: list[str] = Field(
        default_factory=list, description="People who spoke or were mentioned as attending."
    )


def new_item_id() -> str:
    return uuid.uuid4().hex[:12]


class TrackedActionItem(ActionItem):
    """An action item as stored and served: extracted fields plus what people did with it.

    Kept separate from ``ActionItem`` so the schema sent to Claude has no ``id`` or
    ``done`` fields for the model to fill in.
    """

    id: str = Field(default_factory=new_item_id, min_length=1, max_length=64)
    done: bool = False
    edited: bool = Field(default=False, description="Changed by a person after extraction.")


class StoredNotes(MeetingNotes):
    """Notes as persisted and returned by the API, with trackable action items."""

    action_items: list[TrackedActionItem] = Field(default_factory=list)  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def _stable_ids_for_legacy_rows(cls, data: Any) -> Any:
        # Rows saved before items had ids get positional ones, so they stay stable
        # across reads instead of a fresh random id on every load.
        if isinstance(data, dict) and isinstance(data.get("action_items"), list):
            items = []
            for i, item in enumerate(data["action_items"]):
                if isinstance(item, dict) and not item.get("id"):
                    item = {**item, "id": f"item-{i}"}
                items.append(item)
            data = {**data, "action_items": items}
        return data

    @classmethod
    def from_extracted(cls, notes: MeetingNotes) -> StoredNotes:
        return cls.model_validate(
            {
                **notes.model_dump(),
                "action_items": [{**a.model_dump(), "id": new_item_id()} for a in notes.action_items],
            }
        )


class ActionItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=100)
    due_date: dt.date | None = None
    priority: Priority = Priority.medium


class ActionItemPatch(BaseModel):
    """Partial update. Send only the fields to change; ``owner``/``due_date`` may be null to clear."""

    model_config = ConfigDict(extra="forbid")

    task: str | None = Field(default=None, min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=100)
    due_date: dt.date | None = None
    priority: Priority | None = None
    done: bool | None = None

    @model_validator(mode="after")
    def _non_nullable_fields(self) -> ActionItemPatch:
        for name in ("task", "priority", "done"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if not self.model_fields_set:
            raise ValueError("nothing to update")
        return self


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: str | None = None


class Transcript(BaseModel):
    language: str | None = None
    duration_s: float | None = Field(default=None, ge=0)
    segments: list[Segment]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


class JobStatus(StrEnum):
    queued = "queued"
    transcribing = "transcribing"
    extracting = "extracting"
    completed = "completed"
    failed = "failed"


class MeetingSummary(BaseModel):
    """List view of a meeting (no transcript or notes body)."""

    id: str
    filename: str
    status: JobStatus
    title: str | None
    meeting_date: dt.date
    created_at: dt.datetime
    updated_at: dt.datetime
    error: str | None = None


class MeetingDetail(MeetingSummary):
    transcript: Transcript | None = None
    notes: StoredNotes | None = None


class MeetingList(BaseModel):
    items: list[MeetingSummary]
    total: int


class TranscriptIn(BaseModel):
    """Submit an existing transcript (skips audio transcription)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)
    meeting_date: dt.date | None = None
