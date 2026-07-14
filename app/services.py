"""Game state mutations."""

import uuid

from tortoise.transactions import atomic

from app.config import settings
from app.models import Brick, Cursor, Player

CURSOR_FLUSH_INTERVAL = 0.033

# player_id -> (x, y, z). Cursor moves are coalesced here and upserted in one
# statement every CURSOR_FLUSH_INTERVAL.
cursor_buffer: dict[int, tuple[int, int, int]] = {}


@atomic()
async def create_player(name: str, color: str) -> Player:
    """
    Create a new player with a fresh token.
    """
    return await Player.create(
        token=str(uuid.uuid4()),
        name=name,
        color=color,
        is_online=True,
    )


async def mark_player_as_online(player: Player) -> None:
    await Player.filter(id=player.id, is_online=False).update(is_online=True)


@atomic()
async def mark_player_as_offline(player: Player) -> None:
    """
    Flag offline, drop cursor, release held bricks.
    """
    cursor_buffer.pop(player.id, None)
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
        defaults={"created_by": player, "color": player.color},
    )
    return brick if created else None


async def delete_brick(brick: Brick) -> None:
    """
    Delete a brick and close the gap it leaves in its stack.
    """
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
    Release a brick.
    """
    brick.dragged_by_id = None
    await brick.save(update_fields=["dragged_by_id"])


async def update_cursor(player: Player, x: int, y: int, z: int) -> None:
    """
    Update cursor position.
    """
    cursor_buffer[player.id] = (x, y, z)


async def flush_cursors() -> None:
    """
    Upsert every buffered cursor in one statement.
    """
    if not cursor_buffer:
        return

    pending = list(cursor_buffer.items())
    cursor_buffer.clear()

    rows = [
        Cursor(player_id=player_id, x=x, y=y, z=z) for player_id, (x, y, z) in pending
    ]
    await Cursor.bulk_create(
        rows,
        on_conflict=["player_id"],
        update_fields=["x", "y", "z"],
    )
