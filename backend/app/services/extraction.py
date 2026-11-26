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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import anthropic

from ..schemas import ActionItem, Decision, MeetingNotes, Priority, Transcript
from .chunking import Chunk, chunk_transcript
from .transcript_parser import render_for_llm
from .transcription import DEMO_TRANSCRIPT

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


def build_user_message(transcript: Transcript, meeting_date: dt.date, *, part: str | None = None) -> str:
    header = f"Meeting date: {meeting_date.isoformat()} ({meeting_date.strftime('%A')})\n"
    if part:
        header += f"This is {part} of the meeting.\n"
    return f"{header}\n<transcript>\n{render_for_llm(transcript)}\n</transcript>"


CHUNK_PROMPT = """

This transcript is long, so you are seeing one part of it at a time. The user message \
says which part this is and the time range it covers. Write notes for this part only: \
the summary covers what happened in this part, and every decision, action item and \
open question must come from this part. Timestamps are still seconds from the start \
of the whole meeting. Another step will merge the parts, so do not guess about what \
happened before or after this part."""

MERGE_PROMPT = """\
You merge partial meeting notes into one set of notes for the whole meeting. A long \
transcript was split into consecutive, slightly overlapping parts, and each part was \
summarised on its own. You get those partial notes in order, as JSON.

- title: one title for the whole meeting.
- summary: 3-6 sentences on the whole meeting and where it landed, not a list of parts.
- key_points: the main threads of the whole meeting; combine points that repeat.
- decisions: keep every decision. If a later part reverses or changes an earlier \
decision, keep only the final version and say in context what changed.
- action_items: keep every distinct action item. Parts overlap at their edges, so the \
same item can appear twice: merge duplicates into one, keeping the most specific \
owner, due date and the earliest timestamp_s. If a later part reassigns an item or \
moves its deadline, use the later owner or date.
- open_questions: drop any question that a later part answered or turned into a \
decision; keep the rest.
- participants: everyone named in any part, without duplicates.

Use only what the partial notes contain. Do not invent names, dates or commitments, \
and keep timestamps exactly as given."""


def build_merge_message(partials: list[tuple[Chunk, MeetingNotes]], meeting_date: dt.date) -> str:
    parts = "\n\n".join(
        f'<part index="{c.index + 1}" range="{c.label}">\n{notes.model_dump_json()}\n</part>'
        for c, notes in partials
    )
    return (
        f"Meeting date: {meeting_date.isoformat()} ({meeting_date.strftime('%A')})\n"
        f"The meeting was split into {len(partials)} parts.\n\n{parts}"
    )


class ClaudeExtractor:
    """Single call for ordinary meetings; map-reduce over chunks for long ones."""

    def __init__(
        self,
        client: Any,
        *,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        max_tokens: int = 16000,
        max_transcript_chars: int = 2_000_000,
        chunk_chars: int = 200_000,
        chunk_overlap_segments: int = 3,
        chunk_concurrency: int = 4,
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_transcript_chars = max_transcript_chars
        self.chunk_chars = chunk_chars
        self.chunk_overlap_segments = chunk_overlap_segments
        self.chunk_concurrency = max(1, chunk_concurrency)

    def extract(self, transcript: Transcript, *, meeting_date: dt.date) -> MeetingNotes:
        user_message = build_user_message(transcript, meeting_date)
        if len(user_message) > self.max_transcript_chars:
            # Refuse rather than silently truncate: dropping the end of a meeting
            # drops exactly the part where decisions and action items get summarised.
            raise ExtractionError(
                f"transcript is too long ({len(user_message):,} chars, limit {self.max_transcript_chars:,})"
            )
        if len(user_message) <= self.chunk_chars:
            notes = self._call(SYSTEM_PROMPT, user_message)
        else:
            notes = self._extract_chunked(transcript, meeting_date)
        return ground_notes(notes, transcript, meeting_date).notes

    def _extract_chunked(self, transcript: Transcript, meeting_date: dt.date) -> MeetingNotes:
        # Leave room in each window for the date header and the part label.
        budget = max(1000, self.chunk_chars - 500)
        chunks = chunk_transcript(transcript, max_chars=budget, overlap_segments=self.chunk_overlap_segments)
        log.info("long transcript: extracting %d parts, then merging", len(chunks))

        def map_one(chunk: Chunk) -> MeetingNotes:
            msg = build_user_message(chunk.transcript, meeting_date, part=chunk.label)
            partial = self._call(SYSTEM_PROMPT + CHUNK_PROMPT, msg)
            # Ground each part against its own window so a hallucinated owner cannot
            # be "confirmed" by the merge step.
            return ground_notes(partial, chunk.transcript, meeting_date).notes

        # Parts are independent, so run them concurrently; map() keeps their order.
        # The first failure propagates and the meeting can be retried as a whole.
        with ThreadPoolExecutor(max_workers=min(self.chunk_concurrency, len(chunks))) as pool:
            partials = list(pool.map(map_one, chunks))

        return self._call(
            MERGE_PROMPT, build_merge_message(list(zip(chunks, partials, strict=True)), meeting_date)
        )

    def _call(self, system: str, user_message: str) -> MeetingNotes:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
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
        return MeetingNotes.model_validate(notes)


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


def _next_weekday(start: dt.date, weekday: int) -> dt.date:
    """The next given weekday on or after ``start`` (Monday is 0)."""
    return start + dt.timedelta(days=(weekday - start.weekday()) % 7)


def demo_notes(meeting_date: dt.date) -> MeetingNotes:
    """What good notes for ``DEMO_TRANSCRIPT`` look like (used by the offline demo)."""
    friday = _next_weekday(meeting_date, 4)
    next_monday = meeting_date + dt.timedelta(days=7 - meeting_date.weekday())
    return MeetingNotes(
        title="Mobile launch weekly sync",
        summary=(
            "The team reviewed launch readiness for the mobile app. iOS has passed App Store review, "
            "but Android is blocked on the payments SDK upgrade, which Sam will finish by Friday. "
            "To leave a week for beta feedback, the public launch moves from the 3rd to the 10th; "
            "Lee will tell marketing. Crash reporting alerts still need to be set up."
        ),
        key_points=[
            "iOS build passed review; Android is blocked on the payments SDK upgrade.",
            "Marketing planned to launch on the 3rd.",
            "A week of beta feedback is wanted before launch.",
        ],
        decisions=[
            Decision(
                decision="Move the public launch from the 3rd to the 10th.",
                context="Gives a week of beta feedback before going public.",
                timestamp_s=40.0,
            )
        ],
        action_items=[
            ActionItem(
                task="Finish the payments SDK upgrade for Android",
                owner="Sam",
                due_date=friday,
                priority=Priority.high,
                timestamp_s=15.0,
            ),
            ActionItem(
                task="Tell marketing about the new launch date and update the launch brief",
                owner="Lee",
                due_date=meeting_date,
                priority=Priority.medium,
                timestamp_s=40.0,
            ),
            ActionItem(
                task="Set up crash reporting alerts",
                owner="Sam",
                due_date=next_monday,
                priority=Priority.medium,
                timestamp_s=74.0,
            ),
        ],
        open_questions=["Do we still need the press kit from the agency?"],
        participants=["Priya", "Sam", "Lee"],
    )


class FakeExtractor:
    """Deterministic, offline extractor for demos and tests. No API key needed.

    Returns hand-written notes for the built-in demo transcript, and a placeholder
    summary for anything else.
    """

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, transcript: Transcript, *, meeting_date: dt.date) -> MeetingNotes:
        self.calls += 1
        if transcript.segments == DEMO_TRANSCRIPT.segments:
            return demo_notes(meeting_date)
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
        chunk_chars=settings.chunk_chars,
        chunk_overlap_segments=settings.chunk_overlap_segments,
        chunk_concurrency=settings.chunk_concurrency,
    )
