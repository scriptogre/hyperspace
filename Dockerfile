# - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# BUILD STAGE: install dependencies
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0

ENV UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /code

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev

COPY . /code


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# RUNTIME STAGE
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
FROM python:3.14-slim-bookworm

ARG UID=1000
ARG GID=1000
ARG ENVIRONMENT=production
RUN addgroup --gid $GID non-root && \
    adduser --uid $UID --gid $GID --disabled-password --gecos '' non-root

COPY --from=builder --chown=$UID:$GID /usr/local /usr/local
COPY --from=builder --chown=$UID:$GID /code /code

WORKDIR /code

ENV PATH="/usr/local/bin:${PATH}" \
    PYTHONPATH="/code" \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=${ENVIRONMENT}

HEALTHCHECK --interval=30s --timeout=3s --retries=10 --start-period=10s \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8000/health')"

USER non-root
EXPOSE 8000


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# TESTS STAGE: full deps + Playwright (e2e against the running stack)
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
FROM ghcr.io/astral-sh/uv:python3.14-bookworm AS tests

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PATH="/usr/local/bin:${PATH}" \
    PYTHONPATH="/code" \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=testing

WORKDIR /code

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked

RUN playwright install --with-deps chromium

ENTRYPOINT ["pytest"]
