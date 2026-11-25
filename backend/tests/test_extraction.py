from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.schemas import ActionItem, Decision, MeetingNotes, Segment, Transcript
from app.services.extraction import (
    FALLBACK_BETA,
    SYSTEM_PROMPT,
    ClaudeExtractor,
    ExtractionError,
    FakeExtractor,
    build_user_message,
    ground_notes,
)
from app.services.transcription import DEMO_TRANSCRIPT

from .conftest import MEETING_DATE, sample_notes, short_transcript


def _response(parsed: MeetingNotes | None, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        parsed_output=parsed,
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
    )


class FakeMessages:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] | None = None
        self.calls = 0

    def parse(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def fake_client(result: Any) -> tuple[Any, FakeMessages]:
    messages = FakeMessages(result)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def _status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=req), body=None)


def test_calls_claude_with_structured_output_and_fallbacks() -> None:
    client, messages = fake_client(_response(sample_notes()))
    notes = ClaudeExtractor(client, effort="high").extract(DEMO_TRANSCRIPT, meeting_date=MEETING_DATE)

    assert notes.title == "Mobile launch weekly sync"
    kw = messages.kwargs
    assert kw is not None
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_format"] is MeetingNotes
    assert kw["output_config"] == {"effort": "high"}
    assert kw["betas"] == [FALLBACK_BETA]
    assert kw["fallbacks"] == "default"
    assert kw["system"] == SYSTEM_PROMPT
    assert "thinking" not in kw
    assert "temperature" not in kw
    content = kw["messages"][0]["content"]
    assert "Meeting date: 2026-11-25 (Wednesday)" in content
    assert "[0:15] Priya: Sam, can you finish the payments SDK upgrade by Friday?" in content


def test_user_message_wraps_transcript_in_tags() -> None:
    msg = build_user_message(short_transcript(), dt.date(2026, 1, 5))
    assert msg.startswith("Meeting date: 2026-01-05 (Monday)")
    assert "<transcript>\n[0:00] Ana:" in msg
    assert msg.endswith("</transcript>")


def test_extracted_notes_are_grounded() -> None:
    bad = sample_notes().model_copy(
        update={
            "action_items": [ActionItem(task="Do a thing", owner="Zed")],
            "participants": ["Priya", "Zed"],
        }
    )
    client, _ = fake_client(_response(bad))
    notes = ClaudeExtractor(client).extract(DEMO_TRANSCRIPT, meeting_date=MEETING_DATE)
    assert notes.action_items[0].owner is None
    assert notes.participants == ["Priya"]


def test_too_long_transcript_is_rejected_without_calling_api() -> None:
    client, messages = fake_client(_response(sample_notes()))
    with pytest.raises(ExtractionError, match="too long"):
        ClaudeExtractor(client, max_transcript_chars=200).extract(DEMO_TRANSCRIPT, meeting_date=MEETING_DATE)
    assert messages.calls == 0


@pytest.mark.parametrize(
    ("stop_reason", "parsed", "match"),
    [
        ("refusal", None, "declined"),
        ("max_tokens", None, "cut off"),
        ("end_turn", None, "no structured notes"),
    ],
)
def test_bad_stop_reasons_raise(stop_reason: str, parsed: MeetingNotes | None, match: str) -> None:
    client, _ = fake_client(_response(parsed, stop_reason))
    with pytest.raises(ExtractionError, match=match) as ei:
        ClaudeExtractor(client).extract(DEMO_TRANSCRIPT, meeting_date=MEETING_DATE)
    assert ei.value.retryable is False


@pytest.mark.parametrize(
    ("error", "retryable", "match"),
    [
        (_status_error(anthropic.RateLimitError, 429), True, "rate limit"),
        (_status_error(anthropic.AuthenticationError, 401), False, "API key"),
        (_status_error(anthropic.BadRequestError, 400), False, "rejected"),
        (_status_error(anthropic.InternalServerError, 500), True, "HTTP 500"),
        (_status_error(anthropic.NotFoundError, 404), False, "HTTP 404"),
        (
            anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
            True,
            "could not reach",
        ),
    ],
)
def test_api_errors_are_mapped(error: Exception, retryable: bool, match: str) -> None:
    client, _ = fake_client(error)
    with pytest.raises(ExtractionError, match=match) as ei:
        ClaudeExtractor(client).extract(DEMO_TRANSCRIPT, meeting_date=MEETING_DATE)
    assert ei.value.retryable is retryable


class TestGrounding:
    def test_keeps_supported_fields(self) -> None:
        notes = sample_notes()
        result = ground_notes(notes, DEMO_TRANSCRIPT, MEETING_DATE)
        assert result.warnings == []
        assert result.notes == notes

    def test_clears_unknown_owner(self) -> None:
        notes = MeetingNotes(title="t", summary="s", action_items=[ActionItem(task="x", owner="Morgan")])
        result = ground_notes(notes, short_transcript(), MEETING_DATE)
        assert result.notes.action_items[0].owner is None
        assert "Morgan" in result.warnings[0]

    def test_owner_match_is_case_and_whitespace_insensitive_whole_word(self) -> None:
        notes = MeetingNotes(
            title="t",
            summary="s",
            action_items=[ActionItem(task="x", owner="  ben "), ActionItem(task="y", owner="Be")],
        )
        result = ground_notes(notes, short_transcript(), MEETING_DATE)
        assert result.notes.action_items[0].owner == "ben"
        assert result.notes.action_items[1].owner is None  # "Be" is not a whole word in the meeting

    def test_owner_mentioned_only_as_speaker_counts(self) -> None:
        t = Transcript(segments=[Segment(start=0, end=5, speaker="Kim", text="I'll do it.")])
        notes = MeetingNotes(title="t", summary="s", action_items=[ActionItem(task="x", owner="Kim")])
        assert ground_notes(notes, t, MEETING_DATE).notes.action_items[0].owner == "Kim"

    def test_clears_due_date_before_meeting(self) -> None:
        notes = MeetingNotes(
            title="t", summary="s", action_items=[ActionItem(task="x", due_date=dt.date(2026, 11, 1))]
        )
        result = ground_notes(notes, short_transcript(), MEETING_DATE)
        assert result.notes.action_items[0].due_date is None

    def test_clears_timestamps_past_end(self) -> None:
        notes = MeetingNotes(
            title="t",
            summary="s",
            decisions=[Decision(decision="d", timestamp_s=500), Decision(decision="e", timestamp_s=30.5)],
            action_items=[ActionItem(task="x", timestamp_s=30.9)],
        )
        result = ground_notes(notes, short_transcript(), MEETING_DATE)
        assert result.notes.decisions[0].timestamp_s is None
        assert result.notes.decisions[1].timestamp_s == 30.5  # within 1s tolerance
        assert result.notes.action_items[0].timestamp_s == 30.9
        assert len(result.warnings) == 1


def test_fake_extractor_is_offline_and_deterministic() -> None:
    fake = FakeExtractor()
    a = fake.extract(short_transcript(), meeting_date=MEETING_DATE)
    b = fake.extract(short_transcript(), meeting_date=MEETING_DATE)
    assert a == b
    assert fake.calls == 2
    assert a.participants == ["Ana", "Ben"]
    assert "Offline demo" in a.summary


def test_demo_notes_resolve_relative_dates_and_pass_grounding() -> None:
    notes = FakeExtractor().extract(DEMO_TRANSCRIPT, meeting_date=MEETING_DATE)  # a Wednesday
    sdk, brief, alerts = notes.action_items
    assert (sdk.owner, sdk.due_date) == ("Sam", dt.date(2026, 11, 27))  # "by Friday"
    assert (brief.owner, brief.due_date) == ("Lee", MEETING_DATE)  # "today"
    assert alerts.due_date == dt.date(2026, 11, 30)  # "early next week" -> Monday
    assert ground_notes(notes, DEMO_TRANSCRIPT, MEETING_DATE).warnings == []


def test_demo_notes_on_a_friday_are_due_the_same_day() -> None:
    friday = dt.date(2026, 11, 27)
    notes = FakeExtractor().extract(DEMO_TRANSCRIPT, meeting_date=friday)
    assert notes.action_items[0].due_date == friday
    assert notes.action_items[2].due_date == dt.date(2026, 11, 30)
