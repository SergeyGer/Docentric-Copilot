# syntax=docker/dockerfile:1
# Multi-stage build: wheels are produced once, the runtime image stays slim and
# runs as an unprivileged user.

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY packages ./packages
COPY services ./services

RUN pip install --no-cache-dir build==1.2.2.post1 \
    && python -m build --wheel --outdir /build/dist


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DC_DATA_DIR=/data

RUN groupadd --gid 10001 copilot \
    && useradd --uid 10001 --gid copilot --create-home copilot \
    && mkdir -p /data && chown copilot:copilot /data

WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

USER copilot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "docentric_copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
