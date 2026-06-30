"""
Typed shapes for the dict rows handed to templates.
"""

from typing import Annotated, TypedDict

from pydantic import BaseModel, StringConstraints

from app.enums import Color


class PlayerJoinForm(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    color: Color


class BrickRow(TypedDict):
    """
    A brick straight from Tortoise `.values()`, one key per column.
    """

    id: int
    x: int
    y: int
    z: int
    color: str
    created_by_id: int | None
    dragged_by_id: int | None


class PlayerRow(TypedDict):
    """
    A player straight from Tortoise `.values()`, one key per column.
    """

    id: int
    name: str
    color: str
    is_online: bool


class EventRow(TypedDict):
    """
    One activity-feed row, joined to its player.
    """

    id: int
    player_name: str
    player_color: str
    label: str


class CursorRow(TypedDict):
    """
    A cursor joined to its owner's name and color.
    """

    token: str
    grid_x: int
    grid_y: int
    grid_z: int
    name: str
    color: str
