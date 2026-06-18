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
from tortoise.fields.relational import ReverseRelation
from tortoise.models import Model

from app.enums import Color, EventType


class Brick(Model):
    """
    A colored block placed on the isometric grid.
    """

    id = IntField(pk=True)
    x = IntField()
    y = IntField()
    z = IntField()
    color = CharEnumField(Color, max_length=20)

    # Relations
    created_by = ForeignKeyField(
        "models.Player",
        related_name="bricks",
        null=True,
        on_delete=SET_NULL,
        description="player who created this brick",
    )
    dragged_by = ForeignKeyField(
        "models.Player",
        related_name="dragged_brick",
        null=True,
        on_delete=SET_NULL,
        description="player currently dragging this brick",
    )
    events: ReverseRelation[Event]

    class Meta:
        table = "brick"

    @property
    def is_being_dragged(self) -> bool:
        return self.dragged_by_id is not None


class Player(Model):
    """
    A player in the game.
    """

    id = IntField(pk=True)
    token = CharField(max_length=64, unique=True, description="UUID from the cookie")
    name = CharField(max_length=100)
    color = CharEnumField(Color, max_length=20)
    is_online = BooleanField(default=False)

    # Relations
    bricks: ReverseRelation[Brick]
    dragged_brick: ReverseRelation[Brick]
    cursor: ReverseRelation[Cursor]
    events: ReverseRelation[Event]

    class Meta:
        table = "player"


class Cursor(Model):
    """
    Last known grid position for a player's cursor.
    """

    x = IntField()
    y = IntField()
    z = IntField()
    is_active = BooleanField(default=True)
    version = BigIntField(default=0)

    # Relations
    player = OneToOneField(
        "models.Player",
        pk=True,
        on_delete=CASCADE,
        related_name="cursor",
    )

    class Meta:
        table = "cursor"


class Event(Model):
    """
    An entry in the activity feed.
    """

    id = IntField(pk=True)
    type = CharEnumField(EventType, max_length=50)
    created_at = DatetimeField(auto_now_add=True)

    # Relations
    player = ForeignKeyField(
        "models.Player",
        related_name="events",
        on_delete=CASCADE,
    )
    brick = ForeignKeyField(
        "models.Brick",
        related_name="events",
        null=True,
        on_delete=SET_NULL,
    )

    class Meta:
        table = "event"
        ordering = ["-id"]
