"""HTTP routes."""

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Response,
)

from fastapi.responses import RedirectResponse
from multipart_response.starlette import Part, MultipartResponse
from starlette.status import (
    HTTP_204_NO_CONTENT,
)

from app.dependencies import (
    require_available_brick,
    require_brick_dragged_by_current_player,
    get_game_context,
    require_coordinates_on_grid,
    require_current_player,
    require_available_brick_or_204,
    require_htmx_request,
    require_online_player,
)
from app.jinja import render
from app.models import Brick, Player
from app.updates import get_rendered_updates
from app.schemas import PlayerJoinForm
from app.services import (
    delete_brick,
    release_brick,
    create_player,
    create_brick,
    grab_brick,
    update_cursor,
)


router = APIRouter()


# ── Pages ───────────────────────────────────────────────────────────────


@router.get("/")
async def index_page(context: dict = Depends(get_game_context)):
    return render("index.html", context)


@router.post(
    "/join",
    status_code=HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_htmx_request)],
)
async def player_join(
    response: Response,
    form: PlayerJoinForm = Form(...),
):
    player = await create_player(form.name, form.color_seed)

    response.status_code = HTTP_204_NO_CONTENT
    response.headers["HX-Redirect"] = "/"
    response.set_cookie("hyperspace", player.token, max_age=365 * 24 * 3600)

    return response


@router.post(
    "/logout",
    status_code=HTTP_204_NO_CONTENT,
)
async def player_logout(response: RedirectResponse):
    response.headers["HX-Redirect"] = "/"
    response.delete_cookie("hyperspace")


@router.get("/health")
async def health() -> str:
    return "ok"


# ── Streams ─────────────────────────────────────────────────────────────


@router.get(
    "/stream",
    response_class=MultipartResponse,
    dependencies=[Depends(require_online_player, scope="request")],
)
async def stream_endpoint():
    async for html, target, swap in get_rendered_updates():
        yield Part(
            html,
            headers={"HX-Target": target, "HX-Swap": swap},
            media_type="text/html",
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
    brick: Brick = Depends(require_available_brick_or_204),
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
