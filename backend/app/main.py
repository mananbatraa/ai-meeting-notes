"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.deps import AppContainer
from .api.routes import router
from .config import Settings, get_settings
from .db import Database, MeetingRepository
from .services.extraction import NotesExtractor, build_extractor
from .services.pipeline import JobQueue, MeetingProcessor
from .services.transcription import Transcriber, build_transcriber

log = logging.getLogger("app")


def create_app(
    settings: Settings | None = None,
    *,
    transcriber: Transcriber | None = None,
    extractor: NotesExtractor | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_url)
        db.create_all()
        repo = MeetingRepository(db)
        processor = MeetingProcessor(
            repo,
            transcriber or build_transcriber(settings),
            extractor or build_extractor(settings),
            delete_audio=settings.delete_audio_after_processing,
        )
        queue = JobQueue(processor, workers=settings.worker_concurrency)
        app.state.container = AppContainer(settings=settings, repo=repo, queue=queue)
        resumed = queue.resume()
        if resumed:
            log.info("re-queued %d meetings left in flight by a previous run", resumed)
        try:
            yield
        finally:
            queue.shutdown(wait=False)
            db.engine.dispose()

    app = FastAPI(title="AI Meeting Notes", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def run() -> None:  # pragma: no cover - entry point
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)
