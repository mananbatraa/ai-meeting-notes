import datetime as dt

import pytest

from app.schemas import ActionItem, JobStatus, MeetingDetail, MeetingNotes
from app.services.export import to_markdown

from .conftest import sample_notes


def _meeting(notes: MeetingNotes | None) -> MeetingDetail:
    now = dt.datetime(2026, 11, 25, 12, tzinfo=dt.UTC)
    return MeetingDetail(
        id="abc",
        filename="a.wav",
        status=JobStatus.completed,
        title=None,
        meeting_date=dt.date(2026, 11, 25),
        created_at=now,
        updated_at=now,
        notes=notes,
    )


def test_full_markdown() -> None:
    md = to_markdown(_meeting(sample_notes()))
    assert md.startswith("# Mobile launch weekly sync\n")
    assert "**Participants:** Priya, Sam, Lee" in md
    assert "- Move the public launch to the 10th _(0:40)_" in md
    assert "| Update the launch brief | Lee | 2026-11-25 | medium |" in md
    assert "## Open questions\n\n- Do we still need the agency press kit?" in md


def test_minimal_markdown_omits_empty_sections() -> None:
    md = to_markdown(_meeting(MeetingNotes(title="T", summary="S")))
    assert "## Decisions" not in md
    assert "## Action items" not in md
    assert "Participants" not in md


def test_table_cells_are_escaped() -> None:
    notes = MeetingNotes(title="T", summary="S", action_items=[ActionItem(task="a | b\nc")])
    assert "| a \\| b c | Unassigned | - | medium |" in to_markdown(_meeting(notes))


def test_requires_notes() -> None:
    with pytest.raises(ValueError, match="no notes"):
        to_markdown(_meeting(None))
