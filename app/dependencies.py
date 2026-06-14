"""FastAPI dependencies: the session cookie, plus the current game state.

The `get_current_*` functions are injected into routes with `Depends`, and the
broadcast loop calls the same functions directly to re-render a fragment. Bricks
and players are raw `.values()` rows; events and cursors are enriched with the
acting player's name and color (a join the templates can't do).
"""

import uuid

from fastapi import Depends, Request, Response

from app import services
from app.enums import EventType
from app.exceptions import FormErrors
from app.models import Brick, Cursor, Event
from app.schemas import BrickRow, CursorRow, EventRow, PlayerRow

COOKIE_NAME = "hyperspace_id"
RENDERED_EVENTS = 10


def get_form_errors(request: Request, response: Response) -> FormErrors:
    """Pop any validation errors a failed POST left in the signed cookie."""
    return FormErrors.pop(request, response)


async def get_session_key(request: Request, response: Response) -> str:
    """Return the caller's session UUID, issuing a new cookie if they are new."""
    session_key = request.cookies.get(COOKIE_NAME)
    if not session_key:
        session_key = str(uuid.uuid4())
        response.set_cookie(
            COOKIE_NAME,
            session_key,
            max_age=365 * 24 * 3600,
            samesite="lax",
            httponly=False,
        )
    return session_key


async def get_current_bricks() -> list[BrickRow]:
    # Every Brick column is exactly what the grid needs, so values() (all fields).
    return await Brick.all().order_by("id").values()


async def get_current_players() -> list[PlayerRow]:
    return list(services.players.values())


async def get_current_player(
    session_key: str = Depends(get_session_key),
) -> PlayerRow | None:
    """The caller's player, or None if this session hasn't joined yet."""
    return services.players.get(session_key)


async def get_current_events() -> list[EventRow]:
    # The FK lets us pull the actor's name/color in one join, no cache lookup.
    rows = (
        await Event.all()
        .order_by("id")
        .values("id", "type", "player__name", "player__color")
    )
    return [
        {
            "id": row["id"],
            "player_name": row["player__name"],
            "player_color": row["player__color"],
            "label": EventType(row["type"]).label,
        }
        for row in rows[-RENDERED_EVENTS:]
    ]


async def get_current_cursors() -> list[CursorRow]:
    rows = (
        await Cursor.filter(is_active=True)
        .order_by("player_id")
        .values("player__session_key", "player__name", "player__color", "x", "y", "z")
    )
    return [
        {
            "session_key": row["player__session_key"],
            "grid_x": row["x"],
            "grid_y": row["y"],
            "grid_z": row["z"],
            "is_active": True,
            "name": row["player__name"],
            "color": row["player__color"],
        }
        for row in rows
    ]
