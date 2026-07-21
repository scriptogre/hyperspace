"""Typed shapes for the dict rows handed to templates."""

from typing import Annotated, TypedDict

from pydantic import BaseModel, Field, StringConstraints

from app.colors import Oklch


class PlayerJoinForm(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    color_seed: Annotated[int, Field(ge=1, le=100)]


class BrickRow(TypedDict):
    """
    A brick rendered on the grid.
    """

    id: int
    x: int
    y: int
    z: int
    color: Oklch
    created_by_id: int | None
    dragged_by_id: int | None


class PlayerRow(TypedDict):
    """
    A player rendered in the online list.
    """

    id: int
    name: str
    initials: str
    color: Oklch
    is_online: bool


class CursorRow(TypedDict):
    """
    A cursor joined to its player.
    """

    player_id: int
    grid_x: int
    grid_y: int
    grid_z: int
    offset: float
    name: str
    initials: str
    color: Oklch
