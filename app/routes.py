"""HTTP routes."""

from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Header,
    Response,
)

from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.status import HTTP_204_NO_CONTENT
from tortoise.expressions import Q
from tortoise.transactions import atomic

from app.dependencies import (
    require_available_brick,
    require_brick_dragged_by_current_player,
    get_game_context,
    require_admin,
    require_current_player,
    require_player_token,
    require_available_brick_or_204,
    require_htmx_request,
)
from app.broadcast import create_streaming_response
from app.enums import Theme
from app.jinja import render
from app.models import Brick, Cursor, Player, World
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
    response_class=StreamingResponse,
)
async def stream(
    accept_encoding: Annotated[str, Header()] = "",
) -> StreamingResponse:
    """Stream rendered templates as they change."""
    encodings = {
        value.partition(";")[0].strip() for value in accept_encoding.lower().split(",")
    }

    # TODO: Replace this with MultipartResponse
    return create_streaming_response("zstd" in encodings)


# ── Actions ─────────────────────────────────────────────────────────────


@router.patch(
    "/world",
    status_code=HTTP_204_NO_CONTENT,
)
@atomic()
async def world_update(
    size: Annotated[int, Form(ge=1, le=32)],
    theme: Annotated[Literal["system", "light", "dark"], Form()],
    announcement: Annotated[str, Form()] = "",
    _: Player = Depends(require_admin),
):
    # TODO: Clean up slop after the talk
    world = await World.select_for_update().get(id=1)
    if size < world.size:
        await Brick.filter(Q(x__gte=size) | Q(y__gte=size) | Q(z__gte=size)).delete()
        await Cursor.filter(Q(x__gte=size) | Q(y__gte=size)).delete()

    world.size = size
    world.theme = None if theme == "system" else Theme(theme)
    world.announcement = announcement.strip() or None
    await world.save(update_fields=["size", "theme", "announcement"])


@router.post(
    "/bricks",
    status_code=HTTP_204_NO_CONTENT,
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
)
async def cursor_update(
    x: int = Form(...),
    y: int = Form(...),
    z: int = Form(0),
    token: str = Depends(require_player_token),
):
    await update_cursor(token, x, y, z)


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
