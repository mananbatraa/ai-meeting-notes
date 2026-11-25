"""Speech-to-text. The production backend is faster-whisper (CTranslate2)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..schemas import Segment, Transcript

if TYPE_CHECKING:
    from ..config import Settings


class TranscriptionError(RuntimeError):
    """Audio could not be transcribed (bad file, decoder failure, empty speech)."""


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> Transcript: ...


class FasterWhisperTranscriber:
    """Wraps ``faster_whisper.WhisperModel``.

    The model is loaded lazily on first use (loading takes seconds and hundreds of MB)
    and shared across worker threads; faster-whisper's ``transcribe`` is thread-safe.
    """

    def __init__(
        self,
        model_size: str = "base",
        *,
        device: str = "auto",
        compute_type: str = "int8",
        beam_size: int = 5,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model: object | None = None
        self._lock = threading.Lock()

    def _load(self) -> object:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as e:  # pragma: no cover - depends on optional extra
                    raise TranscriptionError(
                        "faster-whisper is not installed; install the 'whisper' extra"
                    ) from e
                self._model = WhisperModel(
                    self.model_size, device=self.device, compute_type=self.compute_type
                )
            return self._model

    def transcribe(self, audio_path: Path) -> Transcript:
        model = self._load()
        try:
            segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
                str(audio_path), beam_size=self.beam_size, vad_filter=True
            )
            segments = [
                Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
                for s in segments_iter
                if s.text.strip()
            ]
        except Exception as e:  # decoder errors surface as many exception types
            raise TranscriptionError(f"could not transcribe audio: {e}") from e
        if not segments:
            raise TranscriptionError("no speech detected in the audio")
        return Transcript(language=info.language, duration_s=round(info.duration, 2), segments=segments)


def _seg(start: float, end: float, speaker: str, text: str) -> Segment:
    return Segment(start=start, end=end, speaker=speaker, text=text)


DEMO_TRANSCRIPT = Transcript(
    language="en",
    duration_s=95.0,
    segments=[
        Segment(
            start=0.0,
            end=6.5,
            speaker="Priya",
            text="Okay, let's start. This is the weekly sync for the mobile launch.",
        ),
        Segment(
            start=6.5,
            end=15.0,
            speaker="Sam",
            text="The iOS build passed review yesterday, but Android is still blocked on the payments SDK upgrade.",  # noqa: E501
        ),
        Segment(
            start=15.0,
            end=24.0,
            speaker="Priya",
            text="Sam, can you finish the payments SDK upgrade by Friday? That's the critical path.",
        ),
        _seg(24.0, 28.0, "Sam", "Yes, I'll have it done by Friday."),
        Segment(
            start=28.0,
            end=40.0,
            speaker="Lee",
            text="Marketing wants to launch on the 3rd. I think we should push to the 10th so we have a week of beta feedback.",  # noqa: E501
        ),
        Segment(
            start=40.0,
            end=52.0,
            speaker="Priya",
            text="Agreed. We're moving the public launch to the 10th. Lee, please tell marketing and update the launch brief today.",  # noqa: E501
        ),
        Segment(
            start=52.0,
            end=62.0,
            speaker="Lee",
            text="Will do. Do we still need the press kit from the agency?",
        ),
        Segment(
            start=62.0,
            end=74.0,
            speaker="Priya",
            text="Not sure yet, let's revisit that next week. Last thing, someone needs to set up crash reporting alerts.",  # noqa: E501
        ),
        Segment(
            start=74.0,
            end=86.0,
            speaker="Sam",
            text="I can take crash alerts after the SDK work, so early next week.",
        ),
        _seg(86.0, 95.0, "Priya", "Great. Thanks everyone."),
    ],
)


class FakeTranscriber:
    """Returns a fixed demo transcript. For local demos and tests without a model."""

    def __init__(self, transcript: Transcript = DEMO_TRANSCRIPT) -> None:
        self.transcript = transcript
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path) -> Transcript:
        self.calls.append(audio_path)
        if not audio_path.exists():
            raise TranscriptionError(f"audio file not found: {audio_path.name}")
        return self.transcript


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.transcriber == "fake":
        return FakeTranscriber()
    return FasterWhisperTranscriber(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        beam_size=settings.whisper_beam_size,
    )
