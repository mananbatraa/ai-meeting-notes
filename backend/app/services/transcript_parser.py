"""Parse user-supplied transcripts (WebVTT, SRT, or "Speaker: text" plain text)."""

from __future__ import annotations

import re

from ..schemas import Segment, Transcript

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE_RE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
_BRACKET_TS_RE = re.compile(rf"^\s*\[{_TS}\]\s*")
_SPEAKER_RE = re.compile(r"^([A-Z][\w .'-]{0,40}?):\s+(.+)$")
_VTT_VOICE_RE = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$")


def _seconds(h: str | None, m: str, s: str, frac: str | None) -> float:
    total = float(int(h or 0) * 3600 + int(m) * 60 + int(s))
    if frac:
        total += int(frac.ljust(3, "0")) / 1000
    return round(total, 3)


def _split_speaker(text: str) -> tuple[str | None, str]:
    vm = _VTT_VOICE_RE.match(text)
    if vm:
        return vm.group(1).strip(), vm.group(2).strip()
    m = _SPEAKER_RE.match(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, text


def _parse_cues(lines: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    i = 0
    while i < len(lines):
        m = _CUE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        start = _seconds(*m.groups()[:4])
        end = _seconds(*m.groups()[4:])
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            body.append(lines[i].strip())
            i += 1
        text = " ".join(body)
        if text:
            speaker, text = _split_speaker(text)
            text = re.sub(r"<[^>]+>", "", text).strip()
            if text:
                segments.append(Segment(start=start, end=max(end, start), text=text, speaker=speaker))
    return segments


def _parse_plain(lines: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        start = segments[-1].end if segments else 0.0
        tm = _BRACKET_TS_RE.match(line)
        if tm:
            start = _seconds(*tm.groups())
            line = line[tm.end() :].strip()
        speaker, text = _split_speaker(line)
        if not text:
            continue
        if segments and start > segments[-1].end:
            # a line's timestamp is also where the previous line ends
            segments[-1] = segments[-1].model_copy(update={"end": start})
        segments.append(Segment(start=start, end=start, text=text, speaker=speaker))
    return segments


def parse_transcript(raw: str) -> Transcript:
    """Parse a transcript. Raises ``ValueError`` if it contains no text."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    is_vtt = bool(lines) and lines[0].lstrip("\ufeff").startswith("WEBVTT")
    if is_vtt or any(_CUE_RE.match(ln) for ln in lines[:50]):
        segments = _parse_cues(lines)
    else:
        segments = _parse_plain(lines)
    if not segments:
        raise ValueError("transcript contains no text")
    duration = max(s.end for s in segments) or None
    return Transcript(segments=segments, duration_s=duration)


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:d}:{sec:02d}"


def render_for_llm(transcript: Transcript) -> str:
    """One line per segment: ``[m:ss] Speaker: text``. Timestamps let the model cite moments."""
    out = []
    for seg in transcript.segments:
        who = f"{seg.speaker}: " if seg.speaker else ""
        out.append(f"[{format_timestamp(seg.start)}] {who}{seg.text.strip()}")
    return "\n".join(out)
