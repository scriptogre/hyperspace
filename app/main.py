"""Hyperspace: real-time hypermedia on FastAPI + Tortoise ORM + Postgres."""

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.exceptions import validation_error_handler
from app.lifespan import lifespan
from app.routes import router


class _DropHealthAccessLog(logging.Filter):
    """
    Hide the periodic /health probe from uvicorn's access log.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.args and len(record.args) >= 3 and record.args[2] == "/health"
        )


logging.getLogger("uvicorn.access").addFilter(_DropHealthAccessLog())


app = FastAPI(
    default_response_class=HTMLResponse, title="Hyperspace", lifespan=lifespan
)

app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")
app.include_router(router)

# Form validation errors redirect back with the messages (PRG)
app.add_exception_handler(RequestValidationError, validation_error_handler)
