"""
FastAPI dependencies for players, bricks, and game state.
"""

from typing import cast

from fastapi import Depends, Form, HTTPException, Request, Response

from app.config import settings
from app.enums import EventType
from app.exceptions import FormErrors, PlayerRequired
from app.models import Brick, Cursor, Event, Player
from app.signals import current_player
from app.schemas import BrickRow, CursorRow, EventRow, PlayerRow


COOKIE_NAME = "hyperspace_id"


def require_coordinates_on_grid(x: int = Form(...), y: int = Form(...)):
    """
    Reject x, y, z coordinates that fall outside the grid.
    """
    if x not in range(settings.GRID_SIZE) or y not in range(settings.GRID_SIZE):
        raise HTTPException(status_code=422, detail="cell off grid")

def get_form_errors(request: Request, response: Response) -> FormErrors:
    """
    Pop any validation errors a failed POST left in the signed cookie.
    """
    return FormErrors.pop(request, response)


async def get_current_player(request: Request) -> Player | None:
    """
    Player for this cookie, or None when not joined.
    """
    token = request.cookies.get(COOKIE_NAME)
    return await Player.filter(token=token).first() if token else None


async def require_player(player: Player | None = Depends(get_current_player)) -> Player:
    """
    Require a joined player. Raises for anonymous requests and records who is
    acting so model signals can attribute the change.
    """
    if not player:
        raise PlayerRequired()

    current_player.set(player)
    return player


async def get_brick(brick_id: int) -> Brick:
    # Prefetch dragged_by so ownership checks can compare Player instances directly.
    return await Brick.get(id=brick_id).select_related("dragged_by")


async def get_available_brick(brick: Brick = Depends(get_brick)) -> Brick:
    """Brick exists and nobody is dragging it."""
    if brick.is_being_dragged:
        raise HTTPException(status_code=409)
    return brick


async def get_dragged_brick(
    player: Player = Depends(require_player),
    brick: Brick = Depends(get_brick),
) -> Brick:
    """
    Brick exists and is being dragged by this player.
    """
    if brick.dragged_by != player:
        raise HTTPException(status_code=403)

    return brick


async def get_current_bricks() -> list[BrickRow]:
    return cast(list[BrickRow], cast(object, await Brick.all().order_by("id").values()))


async def get_current_players() -> list[PlayerRow]:
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


async def get_current_cursors() -> list[CursorRow]:
    rows = cast(
        list[dict],
        await Cursor.filter(is_active=True)
        .order_by("player_id")
        .values("player__token", "player__name", "player__color", "x", "y", "z"),
    )
    return [
        {
            "token": row["player__token"],
            "grid_x": row["x"],
            "grid_y": row["y"],
            "grid_z": row["z"],
            "is_active": True,
            "name": row["player__name"],
            "color": row["player__color"],
        }
        for row in rows
    ]


async def get_game_context(
    player: Player | None = Depends(get_current_player),
    bricks: list[BrickRow] = Depends(get_current_bricks),
    players: list[PlayerRow] = Depends(get_current_players),
    events: list[EventRow] = Depends(get_latest_events),
    cursors: list[CursorRow] = Depends(get_current_cursors),
    form_errors: FormErrors = Depends(get_form_errors),
) -> dict:
    """Full template context for the index page."""
    return {
        "player": player,
        "bricks": bricks,
        "players": players,
        "events": events,
        "cursors": cursors,
        "form_errors": form_errors,
    }
