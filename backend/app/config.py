"""Application settings, loaded from environment variables (prefix ``AMN_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AMN_", env_file=".env", extra="ignore")

    # Storage
    database_url: str = "sqlite:///./data/meetings.db"
    upload_dir: Path = Path("./data/uploads")
    max_upload_mb: int = Field(default=200, ge=1)
    delete_audio_after_processing: bool = True

    # Transcription (faster-whisper)
    transcriber: Literal["whisper", "fake"] = "whisper"
    whisper_model: str = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = Field(default=5, ge=1)

    # Extraction (Claude API)
    extractor: Literal["claude", "fake"] = "claude"
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    claude_max_tokens: int = Field(default=16000, ge=1024)
    claude_timeout_s: float = Field(default=300.0, gt=0)

    # Processing
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    # Hard cap: longer transcripts are refused rather than truncated.
    max_transcript_chars: int = Field(default=2_000_000, ge=1000)
    # Transcripts longer than this are split into parts and merged (map-reduce).
    chunk_chars: int = Field(default=200_000, ge=2000)
    chunk_overlap_segments: int = Field(default=3, ge=0, le=50)
    chunk_concurrency: int = Field(default=4, ge=1, le=16)

    # HTTP
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
