"""Typed shapes for the dict rows handed to templates.

Brick and Player rows come straight from Tortoise `.values()` (1:1 with their
columns); Event and Cursor rows are projections, joined to the actor and
renamed for the template. All are plain dicts at runtime, never ORM objects,
which keeps reads cheap. The TypedDicts give the routes, the broadcast and the
type checker a name for each row's shape.
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


class EventRow(TypedDict):
    id: int
    player_name: str
    player_color: str
    label: str


class CursorRow(TypedDict):
    session_key: str
    grid_x: int
    grid_y: int
    grid_z: int
    is_active: bool
    name: str
    color: str
