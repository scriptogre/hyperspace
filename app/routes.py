"""HTTP and WebSocket routes."""

import json

from fastapi import APIRouter, Depends, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app import broadcast, services
from app.dependencies import (
    COOKIE_NAME,
    get_current_bricks,
    get_current_cursors,
    get_current_events,
    get_current_players,
    get_session_key,
)
from app.enums import Color
from app.jinja import render
from app.schemas import BrickRow, CursorView, EventView, PlayerRow
from app.signals import actor


router = APIRouter()


@router.get("/")
async def index(
    session_key: str = Depends(get_session_key),
    bricks: list[BrickRow] = Depends(get_current_bricks),
    players: list[PlayerRow] = Depends(get_current_players),
    events: list[EventView] = Depends(get_current_events),
    cursors: list[CursorView] = Depends(get_current_cursors),
):
    return render(
        "index.html",
        {
            "bricks": bricks,
            "players": players,
            "events": events,
            "cursors": cursors,
            "current_session_key": session_key,
            "show_player_form": session_key not in services.players,
            "colors": list(Color),
        },
    )


@router.post("/join")
async def join(
    session_key: str = Depends(get_session_key),
    name: str = Form(""),
    color: str = Form(""),
):
    error = await services.join(session_key, name, color)
    if error:
        return render(
            "_player_form.html", {"colors": list(Color), "name": name, "error": error}
        )
    # Refresh the cache so the /ws join gate lets the new player act immediately.
    await services.load_players()
    # Empty body removes the overlay; its absence is the client's "joined" signal.
    return HTMLResponse("")


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

    await services.mark_online(session_key)

    actions = {  # message name -> service call; args arrive already typed
        "create_brick": services.create_brick,
        "delete_brick": services.delete_brick,
        "update_cursor": services.update_cursor,
        "start_drag": services.start_drag,
        "end_drag": services.end_drag,
        "move_brick": services.move_brick,
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
        await services.mark_offline(session_key)
