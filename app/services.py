"""Game state mutations."""

import uuid

from tortoise.transactions import in_transaction

from app.models import Brick, Cursor, Player

MAX_STACK_HEIGHT = 5
CURSOR_FLUSH_INTERVAL = 0.033

# player_id -> (x, y, z). Cursor moves are coalesced here and upserted in one
# statement every CURSOR_FLUSH_INTERVAL.
cursor_buffer: dict[int, tuple[int, int, int]] = {}


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


async def mark_player_as_offline(player: Player) -> None:
    """
    Flag offline, drop cursor, release held bricks.
    """
    cursor_buffer.pop(player.id, None)
    await Player.filter(id=player.id).update(is_online=False)
    await Brick.filter(dragged_by=player).update(dragged_by_id=None)
    await Cursor.filter(player=player).delete()


async def create_brick(player: Player, x: int, y: int) -> Brick | None:
    """Stack a brick on cell (x, y) in the player's color."""
    async with in_transaction():
        height = await Brick.filter(x=x, y=y).count()
        if height >= MAX_STACK_HEIGHT:
            return None
        return await player.bricks.create(x=x, y=y, z=height, color=player.color)


async def delete_brick(brick: Brick) -> Brick:
    """
    Delete a brick and close the gap it leaves in its stack.
    """
    x, y = brick.x, brick.y
    await brick.delete()
    await restack(x, y)
    return brick


async def restack(x: int, y: int) -> None:
    """
    Close gaps in a cell's stack after a brick leaves it.
    """
    bricks = await Brick.filter(x=x, y=y).order_by("z")
    for height, brick in enumerate(bricks):
        if brick.z != height:
            await Brick.filter(id=brick.id).update(z=height)


async def start_drag(player: Player, brick: Brick) -> Brick:
    """
    Begin a drag: mark the brick as held by the caller.
    """
    await Brick.filter(id=brick.id).update(dragged_by=player)
    return brick


async def continue_drag(brick: Brick, x: int, y: int) -> Brick:
    """
    Reposition the held brick to the top of cell (x, y). Fires repeatedly during a drag.
    """
    source_x, source_y = brick.x, brick.y
    new_z = await Brick.filter(x=x, y=y).count()
    await Brick.filter(id=brick.id).update(x=x, y=y, z=new_z)
    await restack(source_x, source_y)
    return brick


async def end_drag(brick: Brick) -> Brick:
    """
    End the drag: release the brick, leaving it where the last reposition put it.
    """
    await Brick.filter(id=brick.id).update(dragged_by_id=None)
    return brick


async def move_cursor(player: Player, x: int, y: int, z: int) -> None:
    """
    Buffer a cursor move; flush_cursors upserts the batch.
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
