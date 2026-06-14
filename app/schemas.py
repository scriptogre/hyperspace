"""Typed shapes for the `.values()` rows handed to templates.

These are plain dicts at runtime (Tortoise `.values()` never materializes ORM
objects, which keeps reads cheap); the TypedDicts give the routes, the broadcast
and the type checker a name for each row's shape.
"""

from typing import TypedDict


class BrickRow(TypedDict):
    id: int
    x: int
    y: int
    z: int
    color: str
    dragged_by_id: int | None


class PlayerRow(TypedDict):
    id: int
    session_key: str
    name: str
    color: str
    is_online: bool


class EventView(TypedDict):
    id: int
    player_name: str
    player_color: str
    label: str


class CursorView(TypedDict):
    session_key: str
    grid_x: int
    grid_y: int
    grid_z: int
    is_active: bool
    name: str
    color: str
