"""Render notes as Markdown for copy-paste into docs, tickets, or chat."""

from __future__ import annotations

from ..schemas import MeetingDetail
from .transcript_parser import format_timestamp


def _ts(seconds: float | None) -> str:
    return f" _({format_timestamp(seconds)})_" if seconds is not None else ""


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(meeting: MeetingDetail) -> str:
    if meeting.notes is None:
        raise ValueError("meeting has no notes yet")
    n = meeting.notes
    out = [f"# {meeting.title or n.title}", "", f"**Date:** {meeting.meeting_date.isoformat()}"]
    if n.participants:
        out.append(f"**Participants:** {', '.join(n.participants)}")
    out += ["", "## Summary", "", n.summary]
    if n.key_points:
        out += ["", "## Key points", ""] + [f"- {p}" for p in n.key_points]
    if n.decisions:
        out += ["", "## Decisions", ""]
        for d in n.decisions:
            line = f"- {d.decision}{_ts(d.timestamp_s)}"
            if d.context:
                line += f"  \n  {d.context}"
            out.append(line)
    if n.action_items:
        out += ["", "## Action items", "", "| Task | Owner | Due | Priority |", "|---|---|---|---|"]
        for a in n.action_items:
            out.append(
                f"| {_escape_cell(a.task)} | {_escape_cell(a.owner or 'Unassigned')} | "
                f"{a.due_date.isoformat() if a.due_date else '-'} | {a.priority.value} |"
            )
    if n.open_questions:
        out += ["", "## Open questions", ""] + [f"- {q}" for q in n.open_questions]
    return "\n".join(out) + "\n"
