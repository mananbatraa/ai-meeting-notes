import pytest

from app.services.transcript_parser import format_timestamp, parse_transcript, render_for_llm

VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.500
<v Alice>Let's get started.</v>

2
00:00:04.500 --> 00:00:09.250
<v Bob>I'll own the <b>migration</b> plan.
It ships Monday.
"""

SRT = """1
00:00:00,000 --> 00:00:03,200
Alice: Morning everyone.

2
00:01:05,500 --> 00:01:10,000
Bob: Budget is approved.
"""


def test_parses_webvtt_with_voice_tags_and_multiline_cues() -> None:
    t = parse_transcript(VTT)
    assert [s.speaker for s in t.segments] == ["Alice", "Bob"]
    assert t.segments[1].text == "I'll own the migration plan. It ships Monday."
    assert t.segments[1].start == 4.5
    assert t.segments[1].end == 9.25
    assert t.duration_s == 9.25


def test_parses_srt_with_speaker_prefixes() -> None:
    t = parse_transcript(SRT)
    assert t.segments[0].speaker == "Alice"
    assert t.segments[1].start == 65.5
    assert t.segments[1].text == "Budget is approved."


def test_parses_bom_prefixed_vtt() -> None:
    t = parse_transcript("﻿" + VTT)
    assert len(t.segments) == 2


def test_plain_text_with_bracket_timestamps_closes_previous_segment() -> None:
    t = parse_transcript("[0:05] Dana: Kickoff.\n\n[1:02:03] Eli: Wrapping up.\n")
    assert t.segments[0].start == 5
    assert t.segments[0].end == 3723
    assert t.segments[1].speaker == "Eli"
    assert t.segments[1].start == 3723


def test_plain_text_without_speakers() -> None:
    t = parse_transcript("first line\nsecond line\n")
    assert [s.text for s in t.segments] == ["first line", "second line"]
    assert all(s.speaker is None for s in t.segments)
    assert t.duration_s is None


def test_lowercase_prefix_is_not_a_speaker() -> None:
    t = parse_transcript("note: this is not a person")
    assert t.segments[0].speaker is None


@pytest.mark.parametrize("raw", ["", "   \n\n", "WEBVTT\n\n"])
def test_empty_transcript_raises(raw: str) -> None:
    with pytest.raises(ValueError, match="no text"):
        parse_transcript(raw)


@pytest.mark.parametrize(("secs", "out"), [(0, "0:00"), (65.9, "1:05"), (3723, "1:02:03")])
def test_format_timestamp(secs: float, out: str) -> None:
    assert format_timestamp(secs) == out


def test_render_for_llm_includes_timestamps_and_speakers() -> None:
    rendered = render_for_llm(parse_transcript(SRT))
    assert rendered.splitlines() == ["[0:00] Alice: Morning everyone.", "[1:05] Bob: Budget is approved."]
