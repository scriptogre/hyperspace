"""HTTP and SSE routes."""

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Request,
    Response,
)

from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.status import (
    HTTP_204_NO_CONTENT,
    HTTP_401_UNAUTHORIZED,
    HTTP_303_SEE_OTHER,
)

from app import broadcast
from app.dependencies import (
    COOKIE_NAME,
    require_available_brick,
    require_brick_dragged_by_current_player,
    get_game_context,
    require_coordinates_on_grid,
    require_current_player,
)
from app.jinja import render
from app.models import Brick, Player
from app.schemas import PlayerJoinForm
from app.services import (
    delete_brick,
    release_brick,
    create_player,
    mark_player_as_offline,
    mark_player_as_online,
    create_brick,
    grab_brick,
    update_cursor,
)
from app.signals import current_player


router = APIRouter()


# ── Pages ───────────────────────────────────────────────────────────────


@router.get("/")
async def index_page(context: dict = Depends(get_game_context)):
    return render("index.html", context)


@router.post("/join")
async def player_join(request: Request, form: PlayerJoinForm = Form(...)):
    player = await create_player(form.name, form.color)

    if request.headers.get("hx-request"):
        response = Response(
            status_code=HTTP_204_NO_CONTENT,
            headers={"HX-Redirect": "/"},
        )
    else:
        response = RedirectResponse(
            "/",
            status_code=HTTP_303_SEE_OTHER,
        )

    response.set_cookie(
        COOKIE_NAME,
        player.token,
        max_age=365 * 24 * 3600,
        samesite="lax",
        httponly=False,
    )
    return response


@router.post(
    "/logout",
    status_code=HTTP_204_NO_CONTENT,
)
async def logout(response: RedirectResponse):
    response.headers["HX-Location"] = "/"
    response.delete_cookie(COOKIE_NAME, path="/", samesite="lax")


@router.get("/health")
async def health() -> str:
    return "ok"


# ── SSE ─────────────────────────────────────────────────────────────────


@router.get("/sse")
async def sse_endpoint(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return Response(status_code=HTTP_401_UNAUTHORIZED)

    player = await Player.filter(token=token).first()
    if not player:
        return Response(status_code=HTTP_401_UNAUTHORIZED)

    current_player.set(player)
    await mark_player_as_online(player)

    return StreamingResponse(
        broadcast.sse_stream(token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
        background=BackgroundTask(mark_player_as_offline, player),
    )


# ── Actions ─────────────────────────────────────────────────────────────


@router.post(
    "/bricks",
    status_code=HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_coordinates_on_grid)],
)
async def brick_create(
    x: int = Form(...),
    y: int = Form(...),
    player: Player = Depends(require_current_player),
):
    await create_brick(player, x, y)


@router.delete(
    "/bricks/{brick_id}",
    status_code=HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_current_player)],
)
async def brick_delete(
    brick: Brick = Depends(require_available_brick),
):
    await delete_brick(brick)


@router.patch(
    "/cursor",
    status_code=HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_coordinates_on_grid)],
)
async def cursor_update(
    x: int = Form(...),
    y: int = Form(...),
    z: int = Form(0),
    player: Player = Depends(require_current_player),
):
    await update_cursor(player, x, y, z)


@router.post(
    "/bricks/{brick_id}/grab",
    status_code=HTTP_204_NO_CONTENT,
)
async def brick_grab(
    player: Player = Depends(require_current_player),
    brick: Brick = Depends(require_available_brick),
):
    await grab_brick(player, brick)


@router.post(
    "/bricks/{brick_id}/release",
    status_code=HTTP_204_NO_CONTENT,
)
async def brick_release(
    brick: Brick = Depends(require_brick_dragged_by_current_player),
):
    await release_brick(brick)
