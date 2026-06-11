"""Hyperspace Python port. FastAPI + Tortoise ORM + SQLite."""

from fastapi.staticfiles import StaticFiles

from app.fasthtml import FastHTML
from app.lifespan import lifespan
from app.routes import router

app = FastHTML(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)
