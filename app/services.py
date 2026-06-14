"""Game state mutations and the in-memory player cache."""

from tortoise.transactions import in_transaction

from app.enums import Color
from app.models import Brick, Cursor, Player

MAX_STACK_HEIGHT = 5
CURSOR_FLUSH_INTERVAL = 0.033

# session_key -> {id, name, color, is_online}. Player rows change rarely; cache them
# so renders skip the player table and a session can resolve to its player id.
players: dict[str, dict] = {}

# session_key -> (x, y, z). Cursor moves are coalesced here and upserted in one
# statement every CURSOR_FLUSH_INTERVAL.
cursor_buffer: dict[str, tuple[int, int, int]] = {}


async def load_players() -> None:
    rows = await Player.all().values("id", "session_key", "name", "color", "is_online")
    players.clear()
    players.update({row["session_key"]: row for row in rows})


async def join(session_key: str, name: str, color: str) -> str | None:
    """Create or rename the player behind this session. Returns an error string on bad input."""
    name = name.strip()
    if not name:
        return "Name cannot be empty"
    try:
        color = Color(color.lower())
    except ValueError:
        return f"Unknown color: {color}"

    player = await Player.get_or_none(session_key=session_key)
    if player:
        player.name = name
        player.color = color
        await player.save(update_fields=["name", "color"])
    else:
        await Player.create(
            session_key=session_key, name=name, color=color, is_online=True
        )
    return None


async def mark_online(session_key: str) -> None:
    """Flag a returning player online. First-time visitors have no row yet."""
    player = await Player.get_or_none(session_key=session_key)
    if player and not player.is_online:
        player.is_online = True
        await player.save(update_fields=["is_online"])


async def mark_offline(session_key: str) -> None:
    """Flag the player offline, drop their cursor, and release any bricks they were dragging."""
    cursor_buffer.pop(session_key, None)

    player = await Player.get_or_none(session_key=session_key)
    if player:
        player.is_online = False
        await player.save(update_fields=["is_online"])
        await Brick.filter(dragged_by_id=player.id).update(dragged_by_id=None)
        await Cursor.filter(player_id=player.id).update(is_active=False)


async def create_brick(session_key: str, x: int, y: int) -> None:
    """Stack a brick on cell (x, y) in the placer's color. No-op if the cell is full."""
    async with in_transaction():
        height = await Brick.filter(x=x, y=y).count()
        if height >= MAX_STACK_HEIGHT:
            return
        player = players.get(session_key)
        color = player["color"] if player else Color.CYAN
        await Brick.create(x=x, y=y, z=height, color=color)


async def delete_brick(session_key: str, brick_id: int) -> str | None:
    brick = await Brick.get_or_none(id=brick_id)
    if not brick:
        return "Brick not found"

    x, y = brick.x, brick.y
    await brick.delete()
    await restack(x, y)
    return None


async def restack(x: int, y: int) -> None:
    """Close gaps in a cell's stack after a brick leaves it."""
    bricks = await Brick.filter(x=x, y=y).order_by("z")
    for height, brick in enumerate(bricks):
        if brick.z != height:
            brick.z = height
            await brick.save(update_fields=["z"])


async def move_brick(session_key: str, brick_id: int, x: int, y: int) -> None:
    """Move a brick the caller is dragging to the top of cell (x, y)."""
    caller = players.get(session_key)
    brick = await Brick.get_or_none(id=brick_id)
    if not caller or not brick or brick.dragged_by_id != caller["id"]:
        return

    source_x, source_y = brick.x, brick.y
    brick.x = x
    brick.y = y
    brick.z = await Brick.filter(x=x, y=y).count()
    await brick.save(update_fields=["x", "y", "z"])
    await restack(source_x, source_y)


async def start_drag(session_key: str, brick_id: int) -> str | None:
    player = players.get(session_key)
    if not player:
        return None
    brick = await Brick.get_or_none(id=brick_id)
    if not brick:
        return "Brick not found"
    if brick.dragged_by_id:
        return "Already being dragged"

    brick.dragged_by_id = player["id"]
    await brick.save(update_fields=["dragged_by_id"])
    return None


async def end_drag(session_key: str) -> None:
    """Release every brick this player holds."""
    player = players.get(session_key)
    if not player:
        return
    for brick in await Brick.filter(dragged_by_id=player["id"]):
        brick.dragged_by_id = None
        await brick.save(update_fields=["dragged_by_id"])


async def update_cursor(session_key: str, x: int, y: int, z: int) -> None:
    """Buffer a cursor move; flush_cursors upserts the batch."""
    cursor_buffer[session_key] = (x, y, z)


async def flush_cursors() -> None:
    """Upsert every buffered cursor in one statement, firing a single broadcast."""
    if not cursor_buffer:
        return

    pending = list(cursor_buffer.items())
    cursor_buffer.clear()

    rows = [
        Cursor(player_id=player["id"], x=x, y=y, z=z, is_active=True)
        for session_key, (x, y, z) in pending
        if (player := players.get(session_key))
    ]
    if rows:
        await Cursor.bulk_create(
            rows,
            on_conflict=["player_id"],
            update_fields=["x", "y", "z", "is_active"],
        )
