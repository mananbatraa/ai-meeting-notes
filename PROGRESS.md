# Progress

Handoff notes between build sessions.

## Status (2026-11-25, evening)

First build done: working backend, frontend, tests, Docker and CI.

**Done**
- FastAPI backend: upload (audio or transcript file), paste transcript, list, detail,
  retry, delete, Markdown export, public config. Uploads streamed with a size cap.
- faster-whisper transcription behind a `Transcriber` protocol (lazy model load).
- Claude extraction with structured outputs (`messages.parse`, `output_format=MeetingNotes`),
  error mapping, refusal/max_tokens handling, server-side refusal fallbacks.
- Grounding check that clears unsupported owners, due dates and timestamps.
- SQLite persistence; thread-pool job queue; restart recovery of in-flight meetings.
- Offline demo mode with realistic notes for a built-in demo meeting.
- React + TypeScript UI: upload/paste, live progress, summary, action items (sorted,
  owner filter), decisions, open questions, transcript with timestamp jump, Markdown
  copy/download, retry, delete.
- Dockerfiles (backend non-root, nginx frontend), docker-compose, GitHub Actions CI.
- README with Mermaid architecture and design decisions; screenshots in `docs/`.

**Tests**
- Backend: 94 passed, 1 skipped (real-Whisper test, runs in CI with espeak-ng).
  ruff and mypy --strict clean.
- Frontend: 49 vitest tests passing; eslint and tsc clean; production build OK.
- Not verified locally: Docker image build and the real Whisper model (the build
  sandbox can't download packages/models); CI covers both.

## Next steps
1. Check the first CI run, especially `whisper-integration` and `docker`.
2. Speaker diarization (who said what) for raw audio; Whisper gives no speakers today,
   which weakens owner extraction for audio uploads.
3. Long meetings: chunk transcripts above the limit and merge notes instead of failing.
4. Playwright end-to-end test of upload -> notes in demo mode.
5. Edit/check off action items in the UI; export to GitHub Issues / Linear.
6. An eval set of real transcripts with expected action items to measure extraction quality.
