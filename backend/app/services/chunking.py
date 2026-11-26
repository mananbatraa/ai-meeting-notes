"""Split long transcripts into overlapping windows for map-reduce extraction.

A single call works well for an ordinary meeting, but a multi-hour workshop or an
all-day offsite either does not fit the context window or produces notes that skim
the middle. Long transcripts are cut into windows on segment boundaries (never in the
middle of someone's sentence), each window is summarised on its own, and the partial
notes are merged by a second call.

Consecutive windows share a few segments of overlap so that an action item assigned
right at a boundary ("Sam, can you..." / "Sure, by Friday") is seen whole by at least
one window. The merge step is told to de-duplicate what the overlap repeats.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import Segment, Transcript
from .transcript_parser import format_timestamp, render_segment


@dataclass(frozen=True)
class Chunk:
    index: int  # 0-based
    total: int
    transcript: Transcript

    @property
    def start_s(self) -> float:
        return self.transcript.segments[0].start

    @property
    def end_s(self) -> float:
        return max(s.end for s in self.transcript.segments)

    @property
    def label(self) -> str:
        return (
            f"part {self.index + 1} of {self.total} "
            f"({format_timestamp(self.start_s)}-{format_timestamp(self.end_s)})"
        )


def chunk_transcript(transcript: Transcript, *, max_chars: int, overlap_segments: int = 3) -> list[Chunk]:
    """Split ``transcript`` into windows whose rendered text is at most ``max_chars``.

    Windows break on segment boundaries. Each window after the first starts with the
    last ``overlap_segments`` segments of the previous one, as long as that still
    leaves room for new material. A single segment longer than ``max_chars`` gets a
    window of its own rather than being cut.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_segments < 0:
        raise ValueError("overlap_segments must be >= 0")

    segments = transcript.segments
    sizes = [len(render_segment(s)) + 1 for s in segments]  # +1 for the newline
    windows: list[list[Segment]] = []
    start = 0
    while start < len(segments):
        end = start
        used = 0
        while end < len(segments) and (end == start or used + sizes[end] <= max_chars):
            used += sizes[end]
            end += 1
        windows.append(segments[start:end])
        if end >= len(segments):
            break
        # Step back for overlap, but always move forward by at least one segment
        # so a window full of huge segments cannot loop forever.
        start = max(end - overlap_segments, start + 1)

    total = len(windows)
    return [
        Chunk(
            index=i,
            total=total,
            transcript=Transcript(language=transcript.language, duration_s=None, segments=w),
        )
        for i, w in enumerate(windows)
    ]
