"""Render context shapes passed to the templates.

Plain dicts at runtime (fast for minijinja), typed for the checker and IDE.
"""

from typing import TypedDict


class Block(TypedDict):
    id: int
    grid_x: int
    grid_y: int
    grid_z: int
    color: str
    is_being_dragged: bool


class User(TypedDict):
    name: str
    color: str
    online: bool


class Cursor(TypedDict):
    name: str
    color: str
    session_id: str
    grid_x: int
    grid_y: int
    grid_z: int


class Log(TypedDict):
    id: int
    user_name: str
    user_color: str
    kind: str


class World(TypedDict):
    blocks: list[Block]
    users: list[User]
    online_count: int
    cursors: list[Cursor]
    logs: list[Log]
    grid_size: int
    known_ids: set[str]
