from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..config import Settings
from ..db import MeetingRepository
from ..services.pipeline import JobQueue


@dataclass
class AppContainer:
    settings: Settings
    repo: MeetingRepository
    queue: JobQueue


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container
