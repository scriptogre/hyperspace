"""Database models."""

from tortoise.fields import (
    CASCADE,
    SET_NULL,
    BigIntField,
    BooleanField,
    CharEnumField,
    CharField,
    DatetimeField,
    ForeignKeyField,
    IntField,
    OneToOneField,
)
from tortoise.models import Model

from app.enums import Color, EventType


class Brick(Model):
    """A colored block placed on the isometric grid."""

    x = IntField()
    y = IntField()
    z = IntField(description="Stack height within the cell")
    color = CharEnumField(Color, max_length=20)
    dragged_by = ForeignKeyField(
        "models.Player",
        related_name="dragging",
        null=True,
        on_delete=SET_NULL,
        description="player currently dragging this brick",
    )

    class Meta:
        table = "brick"


class Player(Model):
    """A player. The session_key persists across sessions via the session cookie."""

    session_key = CharField(
        max_length=100, unique=True, description="UUID from the session cookie"
    )
    name = CharField(max_length=100)
    color = CharEnumField(Color, max_length=20)
    is_online = BooleanField(default=False)

    class Meta:
        table = "player"


class Cursor(Model):
    """Last known grid position for a player's cursor. `version` is stamped by a
    Postgres trigger on every write, turning the table into a change feed."""

    player = OneToOneField(
        "models.Player", pk=True, on_delete=CASCADE, related_name="cursor"
    )
    x = IntField()
    y = IntField()
    z = IntField()
    is_active = BooleanField(default=True)
    version = BigIntField(default=0)

    class Meta:
        table = "cursor"


class Event(Model):
    """An entry in the activity feed. Created and trimmed by app/signals.py."""

    type = CharEnumField(EventType, max_length=50)
    player = ForeignKeyField(
        "models.Player",
        related_name="events",
        on_delete=CASCADE,
        description="the player who triggered it",
    )
    brick = ForeignKeyField(
        "models.Brick",
        related_name="events",
        null=True,
        on_delete=SET_NULL,
        description="brick this event is about, if any",
    )
    created_at = DatetimeField(auto_now_add=True)

    class Meta:
        table = "event"
        ordering = ["id"]
