# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first for layer caching. faster-whisper decodes audio with PyAV,
# which bundles its own FFmpeg libraries, so no system ffmpeg is needed.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra whisper --no-install-project

COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra whisper

RUN useradd --create-home --uid 10001 app && mkdir -p /data /models && chown app:app /data /models
USER app
ENV PATH=/opt/venv/bin:$PATH \
    AMN_DATABASE_URL=sqlite:////data/meetings.db \
    AMN_UPLOAD_DIR=/data/uploads \
    HF_HOME=/models
VOLUME ["/data", "/models"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
