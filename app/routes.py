"""HTTP and WebSocket routes."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from pydantic import StringConstraints

from app import broadcast, services
from app.dependencies import (
    COOKIE_NAME,
    get_current_bricks,
    get_current_cursors,
    get_current_events,
    get_current_player,
    get_current_players,
    get_form_errors,
    get_session_key,
)
from app.enums import Color
from app.exceptions import FormErrors
from app.jinja import render
from app.schemas import BrickRow, CursorRow, EventRow, PlayerRow
from app.services import (
    create_brick,
    create_player,
    delete_brick,
    end_drag,
    mark_player_as_offline,
    mark_player_as_online,
    move_brick,
    refresh_player_cache,
    start_drag,
    update_cursor,
)
from app.signals import actor


router = APIRouter()


@router.get("/")
async def index_page(
    session_key: str = Depends(get_session_key),
    bricks: list[BrickRow] = Depends(get_current_bricks),
    players: list[PlayerRow] = Depends(get_current_players),
    events: list[EventRow] = Depends(get_current_events),
    cursors: list[CursorRow] = Depends(get_current_cursors),
    current_player: PlayerRow | None = Depends(get_current_player),
    errors: FormErrors = Depends(get_form_errors),
):
    return render(
        "index.html",
        {
            "bricks": bricks,
            "players": players,
            "events": events,
            "cursors": cursors,
            "current_session_key": session_key,
            "current_player": current_player,
            "errors": errors,
        },
    )


@router.post("/join")
async def player_join(
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1), Form()
    ],
    color: Annotated[Color, Form()],
    session_key: str = Depends(get_session_key),
):
    await create_player(session_key, name, color)
    # Refresh the cache so the /ws join gate lets the new player act immediately.
    await refresh_player_cache()
    # Boosted POST follows the redirect and morphs the player-free page in.
    return RedirectResponse("/", status_code=303)


@router.get("/health")
async def health() -> str:
    """Liveness probe for the container healthcheck."""
    return "ok"


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    session_key = websocket.cookies.get(COOKIE_NAME)
    if not session_key:
        await websocket.close(code=4001)
        return

    await mark_player_as_online(session_key)

    actions = {  # message name -> service call; args arrive already typed
        "create_brick": create_brick,
        "delete_brick": delete_brick,
        "update_cursor": update_cursor,
        "start_drag": start_drag,
        "end_drag": end_drag,
        "move_brick": move_brick,
    }
    try:
        async with broadcast.client(session_key, websocket):
            while True:
                message = json.loads(await websocket.receive_text())
                action = actions.get(message["fn"])
                if action and session_key in services.players:  # joined players only
                    actor.set(services.players[session_key]["id"])
                    await action(session_key, *message.get("args", []))
    except WebSocketDisconnect:
        pass
    finally:
        await mark_player_as_offline(session_key)
