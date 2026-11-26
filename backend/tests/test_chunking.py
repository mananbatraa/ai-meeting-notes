from __future__ import annotations

import itertools

import pytest

from app.schemas import Segment, Transcript
from app.services.chunking import chunk_transcript
from app.services.transcript_parser import render_segment


def _transcript(n: int, text: str = "word " * 18) -> Transcript:
    return Transcript(
        language="en",
        duration_s=n * 10.0,
        segments=[
            Segment(start=i * 10.0, end=i * 10.0 + 9, speaker=f"S{i % 3}", text=f"{i} {text}")
            for i in range(n)
        ],
    )


def _rendered(t: Transcript) -> int:
    return sum(len(render_segment(s)) + 1 for s in t.segments)


def test_short_transcript_is_one_chunk() -> None:
    t = _transcript(5)
    chunks = chunk_transcript(t, max_chars=10_000)
    assert len(chunks) == 1
    assert chunks[0].transcript.segments == t.segments
    assert chunks[0].label == "part 1 of 1 (0:00-0:49)"


def test_chunks_respect_size_and_cover_every_segment_in_order() -> None:
    t = _transcript(200)
    chunks = chunk_transcript(t, max_chars=1500, overlap_segments=2)
    assert len(chunks) > 5
    assert all(_rendered(c.transcript) <= 1500 for c in chunks)
    assert all(c.total == len(chunks) for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    seen = [s for c in chunks for s in c.transcript.segments]
    starts = sorted({s.start for s in seen})
    assert starts == [s.start for s in t.segments]  # nothing dropped
    assert chunks[0].start_s == 0.0
    assert chunks[-1].end_s == t.segments[-1].end


def test_consecutive_chunks_overlap_by_the_requested_segments() -> None:
    t = _transcript(60)
    chunks = chunk_transcript(t, max_chars=1200, overlap_segments=3)
    for prev, nxt in itertools.pairwise(chunks):
        assert prev.transcript.segments[-3:] == nxt.transcript.segments[:3]


def test_no_overlap() -> None:
    t = _transcript(60)
    chunks = chunk_transcript(t, max_chars=1200, overlap_segments=0)
    assert sum(len(c.transcript.segments) for c in chunks) == 60


def test_oversized_segment_gets_its_own_chunk_and_progress_is_guaranteed() -> None:
    big = Segment(start=0, end=5, text="x" * 5000)
    small = [Segment(start=5 + i, end=6 + i, text="ok") for i in range(3)]
    t = Transcript(segments=[big, *small])
    chunks = chunk_transcript(t, max_chars=100, overlap_segments=10)
    assert chunks[0].transcript.segments == [big]
    assert chunks[-1].transcript.segments[-1] == small[-1]
    assert len(chunks) <= 4  # always advances, even with overlap larger than the window


@pytest.mark.parametrize(("max_chars", "overlap"), [(0, 1), (100, -1)])
def test_invalid_arguments(max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="must be"):
        chunk_transcript(_transcript(3), max_chars=max_chars, overlap_segments=overlap)


def test_render_segment_includes_speaker_and_timestamp() -> None:
    assert render_segment(Segment(start=75, end=80, speaker="Ana", text=" hi ")) == "[1:15] Ana: hi"
    assert render_segment(Segment(start=3725, end=3730, text="x")) == "[1:02:05] x"
