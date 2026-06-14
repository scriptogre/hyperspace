"""Hyperspace: real-time hypermedia on FastAPI + Tortoise ORM + Postgres."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.lifespan import lifespan
from app.routes import router


# 1. Create application
app = FastAPI(
    default_response_class=HTMLResponse, title="Hyperspace", lifespan=lifespan
)

# 2. Mount static files
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

# 3. Include routers
app.include_router(router)
