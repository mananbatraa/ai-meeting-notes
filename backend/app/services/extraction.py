"""Turn a transcript into validated ``MeetingNotes`` with the Claude API.

Claude is called with structured outputs (``output_format=MeetingNotes``), so the
response is constrained to the notes JSON schema and parsed into the Pydantic model
by the SDK. The result is then *grounded* against the transcript: anything the model
could not have taken from the meeting (an owner nobody mentioned, a timestamp past the
end of the audio, a due date before the meeting) is cleared rather than trusted.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import anthropic

from ..schemas import ActionItem, Decision, MeetingNotes, Transcript
from .transcript_parser import render_for_llm

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """\
You turn meeting transcripts into accurate, structured meeting notes for the people \
who attended. The notes are read by busy people deciding what they personally need to \
do next, so precision matters more than coverage.

Work only from the transcript. Each line starts with a [m:ss] timestamp and, when \
known, the speaker's name.

- summary: 3-6 sentences on what the meeting was about and where it landed.
- key_points: the main things discussed, one short sentence each.
- decisions: only things the group actually agreed or someone with authority settled. \
A proposal that was not agreed is not a decision; put unresolved items in open_questions.
- action_items: concrete follow-ups. Start each task with a verb. Set owner only when \
someone was asked to do it or volunteered, using the name as it appears in the \
transcript; otherwise null. Convert relative due dates ("by Friday", "next week", \
"tomorrow") into ISO dates using the meeting date given below; "next week" means the \
Monday of the following week. If no deadline was given, due_date is null. Use priority \
high only for items described as urgent, blocking, or on the critical path.
- timestamp_s: seconds from the start of the meeting where the decision or action item \
came up, taken from the line's timestamp.
- participants: names of people who spoke or were addressed.

Do not invent names, dates, or commitments that are not in the transcript. If the \
transcript is too short or unclear to support a field, leave that list empty."""


class ExtractionError(RuntimeError):
    """Notes could not be produced. ``retryable`` marks transient upstream failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class NotesExtractor(Protocol):
    def extract(self, transcript: Transcript, *, meeting_date: dt.date) -> MeetingNotes: ...


def build_user_message(transcript: Transcript, meeting_date: dt.date) -> str:
    return (
        f"Meeting date: {meeting_date.isoformat()} ({meeting_date.strftime('%A')})\n\n"
        f"<transcript>\n{render_for_llm(transcript)}\n</transcript>"
    )


class ClaudeExtractor:
    def __init__(
        self,
        client: Any,
        *,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        max_tokens: int = 16000,
        max_transcript_chars: int = 600_000,
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_transcript_chars = max_transcript_chars

    def extract(self, transcript: Transcript, *, meeting_date: dt.date) -> MeetingNotes:
        user_message = build_user_message(transcript, meeting_date)
        if len(user_message) > self.max_transcript_chars:
            # Refuse rather than silently truncate: dropping the end of a meeting
            # drops exactly the part where decisions and action items get summarised.
            raise ExtractionError(
                f"transcript is too long ({len(user_message):,} chars, limit {self.max_transcript_chars:,})"
            )
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                output_format=MeetingNotes,
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise ExtractionError("Claude API rate limit reached", retryable=True) from e
        except anthropic.AuthenticationError as e:
            raise ExtractionError("Claude API key is missing or invalid") from e
        except anthropic.BadRequestError as e:
            raise ExtractionError(f"Claude API rejected the request: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ExtractionError(
                f"Claude API error (HTTP {e.status_code})", retryable=e.status_code >= 500
            ) from e
        except anthropic.APIConnectionError as e:
            raise ExtractionError("could not reach the Claude API", retryable=True) from e

        if response.stop_reason == "refusal":
            raise ExtractionError("Claude declined to summarise this transcript")
        if response.stop_reason == "max_tokens":
            raise ExtractionError("notes were cut off by the output token limit")
        notes = response.parsed_output
        if notes is None:
            raise ExtractionError("Claude returned no structured notes")
        log.info(
            "extracted notes model=%s input_tokens=%s output_tokens=%s",
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return ground_notes(MeetingNotes.model_validate(notes), transcript, meeting_date).notes


@dataclass
class GroundingResult:
    notes: MeetingNotes
    warnings: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _name_in(name: str, haystack: str) -> bool:
    """True if every word of ``name`` appears as a whole word in the transcript."""
    words = _norm(name).split()
    return bool(words) and all(re.search(rf"\b{re.escape(w)}\b", haystack) for w in words)


def ground_notes(notes: MeetingNotes, transcript: Transcript, meeting_date: dt.date) -> GroundingResult:
    """Clear fields that are not supported by the transcript."""
    haystack = _norm(" ".join(f"{s.speaker or ''} {s.text}" for s in transcript.segments))
    end = transcript.duration_s or max((s.end for s in transcript.segments), default=0.0)
    warnings: list[str] = []

    def ts(value: float | None, what: str) -> float | None:
        if value is not None and end and value > end + 1:
            warnings.append(f"{what}: timestamp {value}s is past the end of the meeting")
            return None
        return value

    items: list[ActionItem] = []
    for i, item in enumerate(notes.action_items):
        update: dict[str, object] = {"timestamp_s": ts(item.timestamp_s, f"action {i}")}
        if item.owner and not _name_in(item.owner, haystack):
            warnings.append(f"action {i}: owner {item.owner!r} does not appear in the transcript")
            update["owner"] = None
        if item.due_date and item.due_date < meeting_date:
            warnings.append(f"action {i}: due date {item.due_date} is before the meeting")
            update["due_date"] = None
        items.append(item.model_copy(update=update))

    decisions: list[Decision] = [
        d.model_copy(update={"timestamp_s": ts(d.timestamp_s, f"decision {i}")})
        for i, d in enumerate(notes.decisions)
    ]
    participants = [p for p in notes.participants if _name_in(p, haystack)]
    if len(participants) != len(notes.participants):
        warnings.append("dropped participants not named in the transcript")

    for w in warnings:
        log.warning("grounding: %s", w)
    return GroundingResult(
        notes.model_copy(
            update={"action_items": items, "decisions": decisions, "participants": participants}
        ),
        warnings,
    )


class FakeExtractor:
    """Deterministic, offline extractor for demos and tests. No API key needed."""

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, transcript: Transcript, *, meeting_date: dt.date) -> MeetingNotes:
        self.calls += 1
        speakers = list(dict.fromkeys(s.speaker for s in transcript.segments if s.speaker))
        first = transcript.segments[0].text.strip()
        return MeetingNotes(
            title=(first[:60] or "Meeting").rstrip(".,"),
            summary=f"Offline demo summary of a {len(transcript.segments)}-segment meeting. "
            "Set AMN_EXTRACTOR=claude for real notes.",
            key_points=[s.text.strip() for s in transcript.segments[:3]],
            participants=speakers,
        )


def build_extractor(settings: Settings) -> NotesExtractor:
    if settings.extractor == "fake":
        return FakeExtractor()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    client = anthropic.Anthropic(api_key=key, timeout=settings.claude_timeout_s, max_retries=3)
    return ClaudeExtractor(
        client,
        model=settings.claude_model,
        effort=settings.claude_effort,
        max_tokens=settings.claude_max_tokens,
        max_transcript_chars=settings.max_transcript_chars,
    )
