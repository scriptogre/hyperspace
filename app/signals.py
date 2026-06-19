"""Activity-feed events, created automatically from model signals."""

from collections.abc import Iterable
from contextvars import ContextVar

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.signals import post_save, pre_delete

from app.enums import EventType
from app.models import Brick, Event, Player

current_player: ContextVar[Player | None] = ContextVar("current_player", default=None)


@post_save(Brick)
async def on_brick_saved(
    sender: type[Brick],
    brick: Brick,
    created: bool,
    using_db: BaseDBAsyncClient,
    update_fields: Iterable[str] | None,
) -> None:
    player = current_player.get()
    if not player:
        return

    if created:
        await Event.create(type=EventType.BRICK_CREATED, player=player, brick=brick)

    elif set(update_fields or ()) == {"dragged_by_id"}:
        event_type = (
            EventType.DRAG_STARTED if brick.dragged_by_id else EventType.DRAG_ENDED
        )
        await Event.create(
            type=event_type,
            player=player,
            brick=brick,
        )


@pre_delete(Brick)
async def on_brick_deleted(
    sender: type[Brick],
    brick: Brick,
    using_db: BaseDBAsyncClient,
) -> None:
    player = current_player.get()
    if not player:
        return

    await Event.create(type=EventType.BRICK_DELETED, player=player, brick=brick)


@post_save(Player)
async def on_player_saved(
    sender: type[Player],
    player: Player,
    created: bool,
    using_db: BaseDBAsyncClient,
    update_fields: Iterable[str] | None,
) -> None:
    if created:
        await Event.create(type=EventType.PLAYER_JOINED, player=player)

    elif "is_online" in set(update_fields or ()):
        event_type = (
            EventType.PLAYER_JOINED if player.is_online else EventType.PLAYER_LEFT
        )
        await Event.create(type=event_type, player=player)
