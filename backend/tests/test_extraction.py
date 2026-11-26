from __future__ import annotations

import datetime as dt
import re
import threading
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.schemas import ActionItem, Decision, MeetingNotes, Segment, Transcript
from app.services.extraction import (
    CHUNK_PROMPT,
    FALLBACK_BETA,
    MERGE_PROMPT,
    SYSTEM_PROMPT,
    ClaudeExtractor,
    ExtractionError,
    FakeExtractor,
    build_extractor,
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


# --- long meetings: map-reduce over chunks ---------------------------------------


def long_transcript(n: int = 120) -> Transcript:
    """A long meeting where Ana assigns Ben a task early and Cy a task late."""
    segs = [
        Segment(start=i * 20.0, end=i * 20.0 + 19, speaker="Ana", text=f"Point {i}. " * 8) for i in range(n)
    ]
    segs[2] = Segment(start=40, end=59, speaker="Ana", text="Ben, please draft the budget by Friday.")
    segs[-3] = Segment(start=segs[-3].start, end=segs[-3].end, speaker="Cy", text="I will book the venue.")
    return Transcript(language="en", duration_s=n * 20.0, segments=segs)


class RoutingMessages:
    """Answers part calls and the merge call differently; records every request."""

    def __init__(self, *, fail_part: int | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.fail_part = fail_part
        self._lock = threading.Lock()

    def parse(self, **kwargs: Any) -> Any:
        with self._lock:
            self.requests.append(kwargs)
        content: str = kwargs["messages"][0]["content"]
        if kwargs["system"] == MERGE_PROMPT:
            return _response(
                MeetingNotes(
                    title="Offsite planning",
                    summary="Merged summary.",
                    action_items=[
                        ActionItem(task="Draft the budget", owner="Ben", due_date=dt.date(2026, 11, 27)),
                        ActionItem(task="Book the venue", owner="Cy"),
                        ActionItem(task="Order swag", owner="Ghost"),  # not in the meeting
                    ],
                    participants=["Ana", "Ben", "Cy", "Ghost"],
                )
            )
        m = re.search(r"This is part (\d+) of (\d+)", content)
        assert m, "part calls must say which part they are"
        part = int(m.group(1))
        if part == self.fail_part:
            raise _status_error(anthropic.InternalServerError, 503)
        items = []
        if "draft the budget" in content:
            items.append(ActionItem(task="Draft the budget", owner="Ben"))
        if "book the venue" in content:
            # "Ben" is not in this late part: grounding against the part clears it.
            items.append(ActionItem(task="Book the venue", owner="Cy"))
            items.append(ActionItem(task="Review the budget", owner="Ben"))
        return _response(
            MeetingNotes(title=f"Part {part}", summary=f"Part {part} summary.", action_items=items)
        )


def _parts(messages: RoutingMessages) -> list[dict[str, Any]]:
    return [r for r in messages.requests if r["system"] != MERGE_PROMPT]


def test_long_transcript_is_extracted_in_parts_then_merged() -> None:
    messages = RoutingMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    transcript = long_transcript()
    extractor = ClaudeExtractor(client, chunk_chars=3000, chunk_overlap_segments=2)

    notes = extractor.extract(transcript, meeting_date=MEETING_DATE)

    parts = _parts(messages)
    merges = [r for r in messages.requests if r["system"] == MERGE_PROMPT]
    assert len(parts) >= 3
    assert len(merges) == 1
    assert messages.requests[-1]["system"] == MERGE_PROMPT  # merge runs after every part
    assert all(r["system"] == SYSTEM_PROMPT + CHUNK_PROMPT for r in parts)
    assert all(r["output_format"] is MeetingNotes for r in messages.requests)
    for r in parts:
        content = r["messages"][0]["content"]
        assert content.startswith("Meeting date: 2026-11-25 (Wednesday)")
        assert len(content) <= 3000
    numbers = sorted(int(re.search(r"part (\d+) of", r["messages"][0]["content"]).group(1)) for r in parts)  # type: ignore[union-attr]
    assert numbers == list(range(1, len(parts) + 1))

    merge_msg = merges[0]["messages"][0]["content"]
    assert f"split into {len(parts)} parts" in merge_msg
    assert merge_msg.index('<part index="1"') < merge_msg.index(f'<part index="{len(parts)}"')
    assert "Draft the budget" in merge_msg
    assert "Book the venue" in merge_msg
    # The part-level hallucination ("Ben" owning the venue-part item) was cleared before merging.
    assert '"task":"Review the budget","owner":null' in merge_msg

    # Final notes are grounded against the whole transcript.
    assert notes.title == "Offsite planning"
    owners = {i.task: i.owner for i in notes.action_items}
    assert owners == {"Draft the budget": "Ben", "Book the venue": "Cy", "Order swag": None}
    assert notes.participants == ["Ana", "Ben", "Cy"]


def test_transcript_under_chunk_size_makes_a_single_call() -> None:
    client, messages = fake_client(_response(sample_notes()))
    ClaudeExtractor(client, chunk_chars=200_000).extract(long_transcript(), meeting_date=MEETING_DATE)
    assert messages.calls == 1
    assert messages.kwargs is not None
    assert messages.kwargs["system"] == SYSTEM_PROMPT
    assert "This is part" not in messages.kwargs["messages"][0]["content"]


def test_failed_part_fails_the_whole_extraction_and_skips_the_merge() -> None:
    messages = RoutingMessages(fail_part=2)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    with pytest.raises(ExtractionError, match="HTTP 503") as ei:
        ClaudeExtractor(client, chunk_chars=3000, chunk_concurrency=1).extract(
            long_transcript(), meeting_date=MEETING_DATE
        )
    assert ei.value.retryable is True
    assert all(r["system"] != MERGE_PROMPT for r in messages.requests)


def test_hard_limit_still_applies_before_chunking() -> None:
    messages = RoutingMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    with pytest.raises(ExtractionError, match="too long"):
        ClaudeExtractor(client, chunk_chars=3000, max_transcript_chars=5000).extract(
            long_transcript(), meeting_date=MEETING_DATE
        )
    assert messages.requests == []


def test_build_extractor_passes_chunk_settings() -> None:
    s = Settings(
        extractor="claude",
        ANTHROPIC_API_KEY="sk-test",
        chunk_chars=50_000,
        chunk_overlap_segments=5,
        chunk_concurrency=2,
        max_transcript_chars=900_000,
    )
    ex = build_extractor(s)
    assert isinstance(ex, ClaudeExtractor)
    assert (ex.chunk_chars, ex.chunk_overlap_segments, ex.chunk_concurrency) == (50_000, 5, 2)
    assert ex.max_transcript_chars == 900_000
