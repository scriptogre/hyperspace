"""FastAPI dependencies for players, actions, and the world snapshot."""

from collections.abc import AsyncIterator
from random import randrange
from typing import Annotated, Any

from fastapi import Depends, Form, Header, HTTPException, Request, Response
from starlette.status import (
    HTTP_204_NO_CONTENT,
    HTTP_303_SEE_OTHER,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_CONTENT,
)
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from app.colors import calculate_player_color
from app.exceptions import BrickUnavailable, FormErrors, PlayerRequired
from app.models import Brick, Cursor, Player, World
from app.schemas import BrickRow, CursorRow, PlayerRow
from app.services import mark_player_as_offline, mark_player_as_online
from app.signals import current_player


def player_initials(name: str) -> str:
    words = name.split()
    return (
        "".join(word[0] for word in words[:2]).upper()
        if len(words) > 1
        else name[:2].upper()
    )


def require_htmx_request(
    hx_request: Annotated[bool, Header(alias="HX-Request")] = False,
) -> None:
    """Require an htmx request or redirect a regular browser request."""
    if not hx_request:
        raise HTTPException(HTTP_303_SEE_OTHER, headers={"Location": "/"})


async def get_world() -> World:
    """Return the singleton world configuration."""
    return await World.get(id=1)


async def require_coordinates_on_grid(
    x: int = Form(...),
    y: int = Form(...),
    world: World = Depends(get_world),
) -> None:
    """Require x and y coordinates to be inside the current world."""
    if x not in range(world.size) or y not in range(world.size):
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_CONTENT,
            "Position is outside grid",
        )


def get_form_errors(request: Request, response: Response) -> FormErrors:
    """Get validation errors left in the signed cookie by a failed POST."""
    return FormErrors.pop(request, response)


async def get_current_player(request: Request) -> Player | None:
    """Get a player for this cookie, or None when not joined."""
    token = request.cookies.get("hyperspace")
    return await Player.filter(token=token).first() if token else None


async def require_current_player(
    player: Player | None = Depends(get_current_player),
) -> Player:
    """Get a joined (required) player. Raises for anonymous requests."""
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


async def lock_brick(brick_id: int) -> AsyncIterator[Brick | None]:
    """Yield a row-locked brick, or None when absent."""
    async with in_transaction():
        yield await Brick.select_for_update().get_or_none(id=brick_id)


async def require_brick(
    brick: Brick | None = Depends(lock_brick, scope="function"),
) -> Brick:
    """Return the locked brick, or respond with 404."""
    if brick is None:
        raise HTTPException(HTTP_404_NOT_FOUND, "Brick not found")
    return brick


async def get_available_brick(
    brick: Brick | None = Depends(lock_brick, scope="function"),
) -> Brick | None:
    """Return the locked brick unless another player is dragging it."""
    if brick is not None and brick.is_being_dragged:
        raise BrickUnavailable
    return brick


async def require_available_brick(
    brick: Brick | None = Depends(get_available_brick, scope="function"),
) -> Brick:
    """Return an available brick, or respond with 404."""
    if brick is None:
        raise HTTPException(HTTP_404_NOT_FOUND, "Brick not found")
    return brick


async def require_available_brick_or_204(
    brick: Brick | None = Depends(get_available_brick, scope="function"),
) -> Brick:
    """Return an available brick, or stop with 204 when absent."""
    if brick is None:
        raise HTTPException(HTTP_204_NO_CONTENT)
    return brick


async def require_brick_dragged_by_current_player(
    brick: Brick = Depends(require_brick, scope="function"),
    player: Player = Depends(require_current_player),
) -> Brick:
    """Return the locked brick only when the current player is dragging it."""
    if brick.dragged_by_id != player.id:
        raise BrickUnavailable

    return brick


async def get_current_bricks(
    database: BaseDBAsyncClient,
) -> list[BrickRow]:
    rows = (
        await Brick.all(using_db=database)
        .order_by("x", "y", "z")
        .values(
            "id",
            "x",
            "y",
            "z",
            "color_seed",
            "created_by_id",
            "dragged_by_id",
        )
    )
    return [
        {
            "id": row["id"],
            "x": row["x"],
            "y": row["y"],
            "z": row["z"],
            "color": calculate_player_color(row["color_seed"]),
            "created_by_id": row["created_by_id"],
            "dragged_by_id": row["dragged_by_id"],
        }
        for row in rows
    ]


def get_brick_stacks(
    world: World,
    bricks: list[BrickRow],
) -> dict[int, dict[int, list[BrickRow]]]:
    """Bucket each sorted brick into its grid cell."""
    stacks = {x: {y: [] for y in range(world.size)} for x in range(world.size)}
    for brick in bricks:
        stacks[brick["x"]][brick["y"]].append(brick)
    return stacks


async def get_players(
    database: BaseDBAsyncClient,
) -> list[PlayerRow]:
    rows = (
        await Player.all(using_db=database)
        .order_by("name")
        .values("id", "name", "color_seed", "is_online")
    )
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "initials": player_initials(row["name"]),
            "color": calculate_player_color(row["color_seed"]),
            "is_online": row["is_online"],
        }
        for row in rows
    ]


async def get_cursors(
    database: BaseDBAsyncClient,
    bricks: list[BrickRow],
) -> list[CursorRow]:
    stack_tops: dict[tuple[int, int], int] = {}
    for brick in bricks:
        position = (brick["x"], brick["y"])
        stack_tops[position] = max(stack_tops.get(position, -1), brick["z"])

    rows = (
        await Cursor.all(using_db=database)
        .filter(player__is_online=True)
        .order_by("player_id")
        .values(
            "player_id",
            "player__color_seed",
            "player__name",
            "x",
            "y",
            "z",
        )
    )
    position_counts: dict[tuple[int, int, int], int] = {}
    for row in rows:
        position = (row["x"], row["y"], row["z"])
        position_counts[position] = position_counts.get(position, 0) + 1

    position_indexes: dict[tuple[int, int, int], int] = {}
    cursors = []
    for row in rows:
        position = (row["x"], row["y"], row["z"])
        index = position_indexes.get(position, 0)
        position_indexes[position] = index + 1
        cursors.append(
            {
                "player_id": row["player_id"],
                "grid_x": row["x"],
                "grid_y": row["y"],
                "grid_z": max(row["z"], stack_tops.get((row["x"], row["y"]), -1)),
                "offset": index - (position_counts[position] - 1) / 2,
                "name": row["player__name"],
                "initials": player_initials(row["player__name"]),
                "color": calculate_player_color(row["player__color_seed"]),
            }
        )
    return cursors


async def get_world_context() -> dict[str, Any]:
    """Read one consistent snapshot of the complete world."""
    async with in_transaction() as database:
        await database.execute_script("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        world = await World.get(id=1, using_db=database)
        bricks = await get_current_bricks(database)
        players = await get_players(database)
        cursors = await get_cursors(database, bricks)

    return {
        "world": world,
        "brick_stacks": get_brick_stacks(world, bricks),
        "players": players,
        "cursors": cursors,
    }


async def get_game_context(
    world_context: dict[str, Any] = Depends(get_world_context),
    player: Player | None = Depends(get_current_player),
    form_errors: FormErrors = Depends(get_form_errors),
) -> dict[str, Any]:
    """Full template context for the index page."""
    first_color_seed = randrange(1, 101)
    color_seeds = [((first_color_seed + offset - 1) % 100) + 1 for offset in range(5)]
    try:
        selected_color_seed = int(form_errors.data.get("color_seed", color_seeds[0]))
    except ValueError:
        selected_color_seed = color_seeds[0]
    if selected_color_seed not in range(1, 101):
        selected_color_seed = color_seeds[0]
    elif selected_color_seed not in color_seeds:
        color_seeds[0] = selected_color_seed

    available_colors = [
        {"seed": seed, "color": calculate_player_color(seed)} for seed in range(1, 101)
    ]
    available_colors.sort(key=lambda option: option["color"].hue)

    return {
        **world_context,
        "player": player,
        "form_errors": form_errors,
        "selected_color_seed": selected_color_seed,
        "suggested_colors": [
            {"seed": seed, "color": calculate_player_color(seed)}
            for seed in color_seeds
        ],
        "available_colors": available_colors,
    }
