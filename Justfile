up:
    docker compose up -d

down:
    docker compose down

dev:
    uv run uvicorn app.main:app --reload --ws-per-message-deflate false

css:
    bun x @tailwindcss/cli -i static/css/input.css -o static/css/output.css

install:
    uv sync
