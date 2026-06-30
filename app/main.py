"""Hyperspace: real-time hypermedia on FastAPI + Tortoise ORM + Postgres."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from tortoise.exceptions import DoesNotExist

from app.config import settings
from app.exceptions import (
    PlayerRequired,
    not_found_handler,
    player_required_handler,
)
from app.lifespan import lifespan
from app.routes import router

app = FastAPI(
    default_response_class=HTMLResponse,
    title="Hyperspace",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")
app.include_router(router)

app.add_exception_handler(PlayerRequired, player_required_handler)
app.add_exception_handler(DoesNotExist, not_found_handler)
# app.add_exception_handler(RequestValidationError, validation_error_handler)
