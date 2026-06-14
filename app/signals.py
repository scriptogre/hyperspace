"""Activity-feed events, created automatically from model writes.

Service functions never log: they just mutate bricks and players, and the
handlers here turn those writes into Event rows. The WebSocket dispatch stamps
`actor` with the acting player's id before each mutation so brick events can be
attributed; player events use the player's own id.
"""

from contextvars import ContextVar

from tortoise.signals import post_save, pre_delete

from app.enums import EventType
from app.models import Brick, Event, Player

MAX_EVENTS = 40

actor: ContextVar[int | None] = ContextVar("actor", default=None)


@post_save(Brick)
async def on_brick_saved(sender, brick, created, using_db, update_fields) -> None:
    if created:
        await Event.create(
            type=EventType.BRICK_CREATED, player_id=actor.get(), brick_id=brick.id
        )
    elif set(update_fields or ()) == {"dragged_by_id"}:
        event_type = (
            EventType.DRAG_STARTED if brick.dragged_by_id else EventType.DRAG_ENDED
        )
        await Event.create(type=event_type, player_id=actor.get(), brick_id=brick.id)


@pre_delete(Brick)
async def on_brick_deleted(sender, brick, using_db) -> None:
    await Event.create(
        type=EventType.BRICK_DELETED, player_id=actor.get(), brick_id=brick.id
    )


@post_save(Player)
async def on_player_saved(sender, player, created, using_db, update_fields) -> None:
    if created:
        await Event.create(type=EventType.PLAYER_JOINED, player_id=player.id)
    elif "is_online" in set(update_fields or ()):
        event_type = (
            EventType.PLAYER_JOINED if player.is_online else EventType.PLAYER_LEFT
        )
        await Event.create(type=event_type, player_id=player.id)


@post_save(Event)
async def trim_events(sender, event, created, using_db, update_fields) -> None:
    """Keep only the newest MAX_EVENTS events after each insert."""
    if not created:
        return
    cutoff = (
        await Event.all()
        .order_by("-id")
        .offset(MAX_EVENTS)
        .limit(1)
        .values_list("id", flat=True)
    )
    if cutoff:
        await Event.filter(id__lte=cutoff[0]).delete()
