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

from app import broadcast
from app.dependencies import (
    COOKIE_NAME,
    get_available_brick,
    get_dragged_brick,
    get_game_context,
    require_coordinates_on_grid,
    require_player,
)
from app.jinja import render
from app.models import Brick, Player
from app.schemas import PlayerJoinForm
from app.services import (
    continue_drag,
    delete_brick,
    end_drag,
    create_player,
    mark_player_as_offline,
    mark_player_as_online,
    create_brick,
    start_drag,
    move_cursor,
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

    # A boosted submit would innerMorph the next page in, which neither applies the
    # <body> attributes nor fires load triggers, so the SSE stream never connects.
    # HX-Redirect makes htmx do a real navigation; plain posts get a normal 303.
    if request.headers.get("hx-request"):
        response = Response(status_code=204, headers={"HX-Redirect": "/"})
    else:
        response = RedirectResponse("/", status_code=303)

    response.set_cookie(
        COOKIE_NAME,
        player.token,
        max_age=365 * 24 * 3600,
        samesite="lax",
        httponly=False,
    )
    return response


@router.get("/health")
async def health() -> str:
    return "ok"


# ── SSE ─────────────────────────────────────────────────────────────────


@router.get("/sse")
async def sse_endpoint(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return Response(status_code=401)

    player = await Player.filter(token=token).first()
    if not player:
        return Response(status_code=401)

    current_player.set(player)
    await mark_player_as_online(player)

    return StreamingResponse(
        broadcast.sse_stream(token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "zstd",  # browser decodes; client drops fzstd + base64
        },
        background=BackgroundTask(mark_player_as_offline, player),
    )


# ── Actions ─────────────────────────────────────────────────────────────


@router.post(
    "/bricks", status_code=204, dependencies=[Depends(require_coordinates_on_grid)]
)
async def brick_create(
    x: int = Form(...),
    y: int = Form(...),
    player: Player = Depends(require_player),
):
    await create_brick(player, x, y)


@router.delete("/bricks/{brick_id}", status_code=204)
async def brick_delete(
    brick: Brick = Depends(get_available_brick),
):
    await delete_brick(brick)


@router.patch(
    "/cursors", status_code=204, dependencies=[Depends(require_coordinates_on_grid)]
)
async def cursor_move(
    x: int = Form(...),
    y: int = Form(...),
    z: int = Form(...),
    player: Player = Depends(require_player),
):
    await move_cursor(player, x, y, z)


@router.post("/bricks/{brick_id}/drag/start", status_code=204)
async def brick_start_drag(
    player: Player = Depends(require_player),
    brick: Brick = Depends(get_available_brick),
):
    await start_drag(player, brick)


@router.patch(
    "/bricks/{brick_id}/drag/continue",
    status_code=204,
    dependencies=[Depends(require_coordinates_on_grid)],
)
async def brick_continue_drag(
    x: int = Form(...),
    y: int = Form(...),
    brick: Brick = Depends(get_dragged_brick),
):
    await continue_drag(brick, x, y)


@router.post("/bricks/{brick_id}/drag/end", status_code=204)
async def brick_end_drag(
    brick: Brick = Depends(get_dragged_brick),
):
    await end_drag(brick)
