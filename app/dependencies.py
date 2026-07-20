"""
FastAPI dependencies for players, bricks, and game state.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Form, Header, HTTPException, Request, Response
from starlette.status import (
    HTTP_303_SEE_OTHER,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_CONTENT,
)
from tortoise.transactions import in_transaction

from app import broadcast
from app.config import settings
from app.enums import EventType
from app.exceptions import BrickUnavailable, FormErrors, PlayerRequired
from app.models import Brick, Cursor, Event, Player
from app.signals import current_player
from app.services import mark_player_as_offline, mark_player_as_online
from app.schemas import BrickRow, CursorRow, EventRow, PlayerRow


def require_htmx_request(
    hx_request: Annotated[bool, Header(alias="HX-Request")] = False,
) -> None:
    """
    Require an htmx request or redirect a regular browser request.
    """
    if not hx_request:
        raise HTTPException(HTTP_303_SEE_OTHER, headers={"Location": "/"})


def require_coordinates_on_grid(x: int = Form(...), y: int = Form(...)):
    """
    Require x, y, z coordinates to be inside the grid.
    """
    if x not in range(settings.GRID_SIZE) or y not in range(settings.GRID_SIZE):
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_CONTENT,
            "Position is outside grid",
        )


def get_form_errors(request: Request, response: Response) -> FormErrors:
    """
    Get validation errors left in the signed cookie by a failed POST.
    """
    return FormErrors.pop(request, response)


async def get_current_player(request: Request) -> Player | None:
    """
    Get a player for this cookie, or None when not joined.
    """
    token = request.cookies.get("hyperspace")
    return await Player.filter(token=token).first() if token else None


async def require_current_player(
    player: Player | None = Depends(get_current_player),
) -> Player:
    """
    Get a joined (required) player. Raises for anonymous requests.
    """
    if not player:
        raise PlayerRequired

    current_player.set(player)
    return player


async def require_online_player(
    player: Player | None = Depends(get_current_player),
) -> AsyncIterator[Player]:
    """Authenticate a stream and track its online lifetime."""
    if not player:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    current_player.set(player)
    await mark_player_as_online(player)
    try:
        yield player
    finally:
        await mark_player_as_offline(player)


async def subscribe_to_updates(
    player: Player = Depends(require_online_player, scope="request"),
) -> AsyncIterator[asyncio.Queue[str]]:
    """
    Subscribe for the lifetime of an updates connection.
    """
    queue = broadcast.subscribe(player.token)
    for table in ("bricks", "players", "events", "cursors"):
        queue.put_nowait(table)
    try:
        yield queue
    finally:
        broadcast.unsubscribe(player.token)


async def require_brick(brick_id: int) -> AsyncIterator[Brick]:
    """
    Lock a brick for the duration of the route or return 404.
    """
    async with in_transaction():
        brick = await Brick.select_for_update().get_or_none(id=brick_id)

        if brick is None:
            raise HTTPException(HTTP_404_NOT_FOUND, "Brick not found")

        yield brick


async def require_available_brick(
    brick: Brick = Depends(require_brick, scope="function"),
) -> Brick:
    """
    Require a brick that nobody is dragging.
    """
    if brick.is_being_dragged:
        raise BrickUnavailable

    return brick


async def require_brick_dragged_by_current_player(
    brick: Brick = Depends(require_brick, scope="function"),
    player: Player = Depends(require_current_player),
) -> Brick:
    """
    Require a brick currently dragged by the current player.
    """
    if brick.dragged_by_id != player.id:
        raise BrickUnavailable

    return brick


async def get_current_bricks() -> list[BrickRow]:
    return cast(
        list[BrickRow], cast(object, await Brick.all().order_by("x", "y", "z").values())
    )


async def get_brick_stacks() -> dict[int, dict[int, list[BrickRow]]]:
    """Bricks bucketed by cell, each stack sorted by z. Every cell has a list (possibly empty)."""
    bricks = await get_current_bricks()
    brick_stacks: dict[int, dict[int, list[BrickRow]]] = {
        x: {y: [] for y in range(settings.GRID_SIZE)} for x in range(settings.GRID_SIZE)
    }
    for brick in bricks:
        brick_stacks[brick["x"]][brick["y"]].append(brick)
    return brick_stacks


async def get_players() -> list[PlayerRow]:
    return cast(
        list[PlayerRow],
        cast(object, await Player.all().values("id", "name", "color", "is_online")),
    )


async def get_latest_events() -> list[EventRow]:
    rows = cast(
        list[dict],
        await Event.all()
        .order_by("-id")
        .limit(10)
        .values("id", "type", "player__name", "player__color"),
    )
    return [
        {
            "id": row["id"],
            "player_name": row["player__name"],
            "player_color": row["player__color"],
            "label": EventType(row["type"]).label,
        }
        for row in reversed(rows)
    ]


async def get_cursors() -> list[CursorRow]:
    rows = cast(
        list[dict],
        await Cursor.all()
        .order_by("player_id")
        .values("player__token", "player__name", "player__color", "x", "y", "z"),
    )
    return [
        {
            "token": row["player__token"],
            "grid_x": row["x"],
            "grid_y": row["y"],
            "grid_z": row["z"],
            "name": row["player__name"],
            "color": row["player__color"],
        }
        for row in rows
    ]


async def get_game_context(
    player: Player | None = Depends(get_current_player),
    brick_stacks: dict[int, dict[int, list[BrickRow]]] = Depends(get_brick_stacks),
    players: list[PlayerRow] = Depends(get_players),
    events: list[EventRow] = Depends(get_latest_events),
    cursors: list[CursorRow] = Depends(get_cursors),
    form_errors: FormErrors = Depends(get_form_errors),
) -> dict:
    """Full template context for the index page."""
    return {
        "player": player,
        "brick_stacks": brick_stacks,
        "players": players,
        "events": events,
        "cursors": cursors,
        "form_errors": form_errors,
    }
