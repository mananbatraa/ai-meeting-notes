# Progress

Handoff notes between build sessions.

## Status (2026-11-25, 10:40 PM final run) — slot finished

**Done this run (final polish)**
- Playwright end-to-end suite (`frontend/e2e/`, `npm run e2e`): starts the real backend in
  demo mode (fresh temp SQLite + upload dir) and the Vite dev server, then drives Chromium
  through upload -> notes -> check off / edit owner / add / remove action items -> reload
  (proves persistence) -> Markdown download; paste-and-delete; deep link + back button.
  Mutation-checked (dropping the check-off step makes it fail).
- New `e2e` CI job (installs Chromium, uploads the HTML report on failure).
- README test table and commands updated.

**Tests (all passing)**
- Backend: 131 passed, 1 skipped locally with the whisper extra installed (the espeak-ng
  test runs in CI). ruff, ruff format, mypy --strict clean.
- Frontend: 63 vitest passing; eslint and tsc clean.
- Playwright: 3 passing.

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
- Backend: 94 passed, 2 skipped locally (the Whisper tests, which run in the CI
  `whisper-integration` job). ruff and mypy --strict clean.
- The first CI run found a real bug: faster-whisper 1.2.1 breaks on PyAV 19
  (`av.open(metadata_errors=...)` was removed). Fixed by pinning `av<19` in the
  `whisper` extra, with a model-free regression test that decodes a WAV.
- CI is green on all four jobs (backend, frontend, whisper-integration with the real
  `tiny.en` model, docker compose build).
- Frontend: 49 vitest tests passing; eslint and tsc clean; production build OK.
- Docker images build in CI. The real Whisper model can't be downloaded in the build
  sandbox, so the end-to-end transcription test only runs in CI.

## Status (2026-11-25, late afternoon run)

**Done this run**
- Long meetings: transcripts over `AMN_CHUNK_CHARS` (200k chars) are split into
  segment-aligned, overlapping parts (`services/chunking.py`), extracted concurrently,
  grounded per part, merged by a second Claude call (`MERGE_PROMPT`) and grounded again
  against the full transcript. Hard cap raised to 2M chars (still refuses, never truncates).
- Action item editing: stored notes are `StoredNotes` / `TrackedActionItem` (stable `id`,
  `done`, `edited`), kept out of the schema sent to Claude. New endpoints
  `POST /api/meetings/{id}/action-items`, `PATCH|DELETE .../action-items/{item_id}`.
  Atomic read-modify-write under a lock (race test fails without it). Old rows without ids
  get stable positional ids (`item-N`). Markdown export has a Done column.
- UI: done checkboxes (optimistic, rolled back on error), inline edit sending only changed
  fields, add/remove, hide-done filter and "N of M done". Screenshot `docs/notes.png` updated.
- README: features, API examples, config table, design notes, map-reduce diagram, test counts.

**Tests**
- Backend: 130 passed, 2 skipped locally (Whisper tests run in CI). ruff, ruff format,
  mypy --strict clean.
- Frontend: 63 vitest tests passing; eslint and tsc clean; production build OK.

## Next steps
1. Speaker diarization (who said what) for raw audio; Whisper gives no speakers today,
   which weakens owner extraction for audio uploads.
2. Export action items to GitHub Issues / Linear.
3. Show chunk progress ("part 3 of 8") while a long meeting is extracting.
4. An eval set of real transcripts with expected action items to measure extraction quality.
