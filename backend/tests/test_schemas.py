import datetime as dt

import pytest
from pydantic import ValidationError

from app.schemas import ActionItem, MeetingNotes, Priority


def test_blank_owner_becomes_none() -> None:
    assert ActionItem(task="Do it", owner="  ").owner is None
    assert ActionItem(task="Do it", owner=" Sam ").owner == "Sam"


def test_due_date_parses_iso_string() -> None:
    item = ActionItem.model_validate({"task": "Ship", "due_date": "2026-12-01", "priority": "high"})
    assert item.due_date == dt.date(2026, 12, 1)
    assert item.priority is Priority.high


@pytest.mark.parametrize(
    "payload",
    [
        {"task": ""},
        {"task": "x", "due_date": "next friday"},
        {"task": "x", "priority": "urgent"},
        {"task": "x", "timestamp_s": -1},
        {"task": "x", "assignee": "Sam"},
    ],
)
def test_invalid_action_items_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ActionItem.model_validate(payload)


def test_notes_require_title_and_summary() -> None:
    with pytest.raises(ValidationError):
        MeetingNotes.model_validate({"title": "", "summary": "x"})
    notes = MeetingNotes.model_validate({"title": "T", "summary": "S"})
    assert notes.action_items == []
    assert notes.decisions == []


def test_notes_json_schema_is_closed() -> None:
    schema = MeetingNotes.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["ActionItem"]["additionalProperties"] is False
