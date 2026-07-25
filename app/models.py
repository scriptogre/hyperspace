"""Database models."""

from tortoise.fields import (
    CASCADE,
    SET_NULL,
    BooleanField,
    CharEnumField,
    CharField,
    TextField,
    ForeignKeyField,
    IntField,
    OneToOneField,
)
from tortoise.fields.relational import ReverseRelation
from tortoise.models import Model

from app.colors import Oklch, calculate_player_color
from app.enums import Theme


class World(Model):
    """The singleton world configuration."""

    id = IntField(pk=True, generated=False, default=1)
    theme = CharEnumField(Theme, max_length=5, null=True)
    size = IntField(default=12)
    announcement = TextField(null=True)

    class Meta:
        table = "worlds"


class Brick(Model):
    """
    A colored block placed on the isometric grid.
    """

    id = IntField(pk=True)
    x = IntField()
    y = IntField()
    z = IntField()
    color_seed = IntField()

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

    class Meta:
        table = "bricks"
        ordering = ["x", "y", "z"]
        unique_together = (("x", "y", "z"),)

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
    color_seed = IntField()
    is_online = BooleanField(default=False)

    # Relations
    bricks: ReverseRelation[Brick]
    dragged_brick: ReverseRelation[Brick]
    cursor: ReverseRelation["Cursor"]

    @property
    def color(self) -> Oklch:
        return calculate_player_color(self.color_seed)

    class Meta:
        table = "players"


class Cursor(Model):
    """
    Last known grid position for a player's cursor.
    """

    x = IntField()
    y = IntField()
    z = IntField()

    # Relations
    player = OneToOneField(
        "models.Player",
        pk=True,
        on_delete=CASCADE,
        related_name="cursor",
    )

    class Meta:
        table = "cursors"
