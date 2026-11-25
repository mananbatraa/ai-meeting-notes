import pytest

from app.config import Settings
from app.services.extraction import ClaudeExtractor, FakeExtractor, build_extractor


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMN_CLAUDE_EFFORT", "high")
    monkeypatch.setenv("AMN_MAX_UPLOAD_MB", "50")
    monkeypatch.setenv("AMN_CORS_ORIGINS", '["https://notes.example.com"]')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.claude_effort == "high"
    assert s.max_upload_mb == 50
    assert s.cors_origins == ["https://notes.example.com"]
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-test"
    assert "sk-test" not in repr(s)


def test_defaults_use_current_opus_model() -> None:
    assert Settings(_env_file=None).claude_model == "claude-opus-5-5"


def test_invalid_effort_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMN_CLAUDE_EFFORT", "extreme")
    with pytest.raises(ValueError, match="claude_effort"):
        Settings(_env_file=None)


def test_build_extractor() -> None:
    assert isinstance(build_extractor(Settings(extractor="fake")), FakeExtractor)
    ex = build_extractor(Settings(extractor="claude", anthropic_api_key="sk-x", claude_effort="low"))
    assert isinstance(ex, ClaudeExtractor)
    assert ex.effort == "low"
    assert ex.client.max_retries == 3
