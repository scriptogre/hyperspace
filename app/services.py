"""Game state: queries and mutations."""

import asyncio

from tortoise import connections

from app.models import COLORS, Brick, Cursor, Event, User

_MAX_EVENT_LOGS = 40
_MAX_STACK_HEIGHT = 5
_MAX_RENDERED_LOGS = 10
GRID_SIZE = 12

# Cursor writes are coalesced: handlers buffer positions, a background task
# upserts every dirty cursor in one statement at this interval.
CURSOR_FLUSH_INTERVAL = 0.033
_cursor_buffer: dict[str, tuple[int, int, int]] = {}


# --- Read model ---

# Player names/colors change rarely; cache them in memory so the per-round
# cursor and stage renders never re-query the user table. The broadcast loop
# reloads this whenever the user table changes.
players: dict[str, dict] = {}


async def load_players() -> None:
    """Reload the in-memory player map from the user table."""
    rows = await User.all().values("identity", "name", "color", "online")
    players.clear()
    players.update({row["identity"]: row for row in rows})


def known_ids() -> set[str]:
    """Identities the server has on record, used to gate the setup modal."""
    return set(players)


def _cursor_view(row: dict) -> dict:
    player = players.get(row["identity"])
    return {
        "session_id": row["identity"],
        "grid_x": row["x"],
        "grid_y": row["y"],
        "grid_z": row["z"],
        "active": row.get("active", True),
        "name": player["name"] if player else "?",
        "color": player["color"].lower() if player else "cyan",
    }


async def cursor_state() -> dict:
    """Full set of active cursors, for the initial render on connect."""
    rows = await Cursor.filter(active=True).order_by("identity").values("identity", "x", "y", "z")
    return {"cursors": [_cursor_view(r) for r in rows], "grid_size": GRID_SIZE}


async def cursor_delta(after: int) -> tuple[list[dict], int]:
    """Cursors changed since `after`. Postgres is the change feed: a monotonic
    version column means 'what changed' is just a WHERE clause."""
    rows = await Cursor.filter(version__gt=after).order_by("version").values(
        "identity", "x", "y", "z", "active", "version"
    )
    watermark = rows[-1]["version"] if rows else after
    return [_cursor_view(r) for r in rows], watermark


async def max_cursor_version() -> int:
    """Current high-water mark, so a fresh broadcast loop skips existing history."""
    rows = await Cursor.all().order_by("-version").limit(1).values_list("version", flat=True)
    return rows[0] if rows else 0


async def stage_state() -> dict:
    """Context for the grid, bricks, HUD and log. Player data comes from the cache."""
    bricks, events = await asyncio.gather(
        Brick.all().order_by("id").values("id", "x", "y", "z", "color", "dragged_by"),
        Event.all().order_by("id").values("id", "kind", "identity"),
    )

    blocks = [
        {
            "id": brick["id"],
            "grid_x": brick["x"],
            "grid_y": brick["y"],
            "grid_z": brick["z"],
            "color": brick["color"].lower(),
            "is_being_dragged": brick["dragged_by"] is not None,
        }
        for brick in bricks
    ]

    logs = []
    for entry in events[-_MAX_RENDERED_LOGS:]:
        player = players.get(entry["identity"])
        logs.append({
            "id": entry["id"],
            "user_name": player["name"] if player else "Someone",
            "user_color": player["color"].lower() if player else "cyan",
            "kind": entry["kind"],
        })

    everyone = list(players.values())
    return {
        "blocks": blocks,
        "users": [{"name": p["name"], "color": p["color"].lower(), "online": p["online"]} for p in everyone],
        "online_count": sum(1 for p in everyone if p["online"]),
        "logs": logs,
        "grid_size": GRID_SIZE,
    }


async def page_state() -> dict:
    """Combined context for the initial full-page render."""
    return (await stage_state()) | (await cursor_state())


# --- Internal helpers ---


async def _restack_cell(x: int, y: int) -> None:
    """Compact z-coordinates in a cell after a brick is removed or moved out."""
    bricks = await Brick.filter(x=x, y=y).order_by("z")
    for i, brick in enumerate(bricks):
        if brick.z != i:
            brick.z = i
            await brick.save(update_fields=["z"])


_TRIM_EVENTS = (
    "DELETE FROM event WHERE id <= "
    "(SELECT id FROM event ORDER BY id DESC OFFSET $1 LIMIT 1)"
)


async def _log(session_id: str, kind: str, brick_id: int | None = None) -> None:
    """Append an event, then trim to the newest _MAX_EVENT_LOGS rows in one delete."""
    await Event.create(kind=kind, identity=session_id, brick_id=brick_id)
    await connections.get("default").execute_query(_TRIM_EVENTS, [_MAX_EVENT_LOGS])


# --- Lifecycle ---


async def on_connect(session_id: str) -> None:
    """Mark a returning player online. New visitors get no DB change here."""
    player = await User.get_or_none(identity=session_id)
    if player:
        player.online = True
        await player.save(update_fields=["online"])
        await _log(session_id, "UserConnected")


async def on_disconnect(session_id: str) -> None:
    """Mark the player offline, release their dragged bricks, and remove their cursor."""
    _cursor_buffer.pop(session_id, None)

    player = await User.get_or_none(identity=session_id)
    if player:
        player.online = False
        await player.save(update_fields=["online"])

    await Cursor.filter(identity=session_id).update(active=False)
    await Brick.filter(dragged_by=session_id).update(dragged_by=None)

    await _log(session_id, "UserDisconnected")


# --- Mutations ---


async def complete_setup(session_id: str, name: str, color: str) -> str | None:
    """Create or update the player record, or return an error string."""
    name = name.strip()
    if not name:
        return "Name cannot be empty"

    color = color.capitalize()
    if color not in COLORS:
        return f"Unknown color: {color}"

    player = await User.get_or_none(identity=session_id)
    if player:
        player.name = name
        player.color = color
        player.online = True
        await player.save(update_fields=["name", "color", "online"])
    else:
        await User.create(identity=session_id, name=name, color=color, online=True)
        await _log(session_id, "UserConnected")

    return None


_INSERT_BRICK = f"""
INSERT INTO brick (x, y, z, color)
SELECT $1, $2,
       (SELECT COUNT(*) FROM brick WHERE x = $1 AND y = $2),
       COALESCE((SELECT color FROM "user" WHERE identity = $3), 'Cyan')
WHERE (SELECT COUNT(*) FROM brick WHERE x = $1 AND y = $2) < {_MAX_STACK_HEIGHT}
"""


async def create_brick(session_id: str, x: int, y: int) -> None:
    """Place a brick at (x, y) in one statement. No-ops if the cell holds 5."""
    affected, _ = await connections.get("default").execute_query(_INSERT_BRICK, [x, y, session_id])
    if affected:
        await _log(session_id, "BrickCreated")


async def delete_brick(session_id: str, brick_id: int) -> str | None:
    """Delete a brick and restack its cell. Returns an error string if not found."""
    brick = await Brick.get_or_none(id=brick_id)
    if not brick:
        return "Brick not found"

    x, y = brick.x, brick.y
    await brick.delete()
    await _restack_cell(x, y)
    await _log(session_id, "BrickDeleted", brick_id)
    return None


async def set_name(session_id: str, name: str) -> str | None:
    """Rename the player. Returns an error string on bad input."""
    name = name.strip()
    if not name:
        return "Name cannot be empty"

    player = await User.get_or_none(identity=session_id)
    if not player:
        return "Player not found"

    player.name = name
    await player.save(update_fields=["name"])
    return None


async def set_color(session_id: str, color: str) -> str | None:
    """Change the player's color. Returns an error string on bad input."""
    color = color.capitalize()
    if color not in COLORS:
        return f"Unknown color: {color}"

    player = await User.get_or_none(identity=session_id)
    if not player:
        return "Player not found"

    player.color = color
    await player.save(update_fields=["color"])
    return None


async def update_cursor(session_id: str, x: int, y: int, z: int) -> None:
    """Buffer the cursor position; flush_cursors upserts every dirty cursor at once."""
    _cursor_buffer[session_id] = (x, y, z)


async def flush_cursors() -> None:
    """Upsert all buffered cursors in a single statement, firing one broadcast."""
    if not _cursor_buffer:
        return

    pending = list(_cursor_buffer.items())
    _cursor_buffer.clear()

    await Cursor.bulk_create(
        [Cursor(identity=i, x=x, y=y, z=z, active=True) for i, (x, y, z) in pending],
        on_conflict=["identity"],
        update_fields=["x", "y", "z", "active"],
    )


async def start_drag(session_id: str, brick_id: int) -> str | None:
    """Lock a brick for dragging by this player."""
    brick = await Brick.get_or_none(id=brick_id)
    if not brick:
        return "Brick not found"
    if brick.dragged_by:
        return "Already being dragged"

    brick.dragged_by = session_id
    await brick.save(update_fields=["dragged_by"])
    await _log(session_id, "DragStarted", brick_id)
    return None


async def end_drag(session_id: str) -> None:
    """Release all bricks this player is dragging."""
    dragging = await Brick.filter(dragged_by=session_id)
    for brick in dragging:
        brick.dragged_by = None
        await brick.save(update_fields=["dragged_by"])
        await _log(session_id, "DragEnded", brick.id)


async def move_brick(session_id: str, brick_id: int, x: int, y: int) -> None:
    """Move a brick the player is currently dragging to a new cell."""
    brick = await Brick.get_or_none(id=brick_id)
    if not brick or brick.dragged_by != session_id:
        return

    src_x, src_y = brick.x, brick.y
    brick.x = x
    brick.y = y
    brick.z = await Brick.filter(x=x, y=y).count()
    await brick.save(update_fields=["x", "y", "z"])
    await _restack_cell(src_x, src_y)
