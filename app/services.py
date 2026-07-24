"""Game state mutations."""

import uuid

from tortoise.transactions import atomic

from app.config import settings
from app.models import Brick, Cursor, Player


@atomic()
async def create_player(name: str, color_seed: int) -> Player:
    """
    Create a new player with a fresh token.
    """
    return await Player.create(
        token=str(uuid.uuid4()),
        name=name,
        color_seed=color_seed,
        is_online=True,
    )


async def mark_player_as_online(player: Player) -> None:
    await Player.filter(id=player.id, is_online=False).update(is_online=True)


@atomic()
async def mark_player_as_offline(player: Player) -> None:
    """
    Flag offline, drop cursor, release held bricks.
    """
    await Player.filter(id=player.id).update(is_online=False)
    await Brick.filter(dragged_by=player).update(dragged_by_id=None)
    await Cursor.filter(player=player).delete()


@atomic()
async def create_brick(player: Player, x: int, y: int) -> Brick | None:
    """
    Add a brick at the top of (x, y) position.
    """
    height = await Brick.filter(x=x, y=y).count()

    if height >= settings.GRID_SIZE:
        return None

    brick, created = await Brick.get_or_create(
        x=x,
        y=y,
        z=height,
        defaults={"created_by": player, "color_seed": player.color_seed},
    )
    return brick if created else None


@atomic()
async def delete_brick(brick: Brick) -> None:
    """Delete a brick and close the gap it leaves in its stack."""
    await brick.delete()
    await restack(brick.x, brick.y)


async def restack(x: int, y: int) -> None:
    """
    Close gaps in a cell's stack after a brick leaves it.
    """
    bricks = await Brick.filter(x=x, y=y).order_by("z")

    for height, brick in enumerate(bricks):
        if brick.z != height:
            await Brick.filter(id=brick.id).update(z=height)


async def grab_brick(player: Player, brick: Brick) -> None:
    """
    Grab a brick.
    """
    brick.dragged_by_id = player.id
    await brick.save(update_fields=["dragged_by_id"])


async def release_brick(brick: Brick) -> None:
    """
    Place a dragged brick at its player's cursor and release it.
    """
    cursor = await Cursor.filter(player_id=brick.dragged_by_id).first()
    if cursor and (brick.x, brick.y) != (cursor.x, cursor.y):
        height = await Brick.filter(x=cursor.x, y=cursor.y).count()
        if height < settings.GRID_SIZE:
            previous_x, previous_y = brick.x, brick.y
            brick.x = cursor.x
            brick.y = cursor.y
            brick.z = height
            await brick.save(update_fields=["x", "y", "z"])
            await restack(previous_x, previous_y)

    brick.dragged_by_id = None
    await brick.save(update_fields=["dragged_by_id"])


@atomic()
async def update_cursor(player: Player, x: int, y: int, z: int) -> None:
    """Store the latest cursor position while the player is online."""
    locked_player = await Player.select_for_update().get(id=player.id)
    if not locked_player.is_online:
        return

    await Cursor.bulk_create(
        [Cursor(player_id=player.id, x=x, y=y, z=z)],
        update_fields=("x", "y", "z"),
        on_conflict=("player_id",),
    )
