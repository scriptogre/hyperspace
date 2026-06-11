"""
Database models. Mirrors the Rust table definitions in models.rs.
"""

from tortoise.fields import BigIntField, BooleanField, CharField, DatetimeField, IntField
from tortoise.models import Model

COLORS = ["Cyan", "Purple", "Orange", "Green", "Pink", "Yellow"]


class Brick(Model):
    """A colored block placed on the isometric grid."""

    id = IntField(pk=True)
    x = IntField()
    y = IntField()
    z = IntField(description="Stack height within the cell")
    color = CharField(max_length=20, description="One of COLORS")
    dragged_by = CharField(
        max_length=100,
        null=True,
        description="Session UUID of the user currently dragging this brick",
    )

    class Meta:
        table = "brick"


class User(Model):
    """A player. Created on first complete_setup call; identity persists across sessions."""

    identity = CharField(max_length=100, pk=True, description="UUID from the session cookie")
    name = CharField(max_length=100)
    color = CharField(max_length=20, description="One of COLORS")
    online = BooleanField(default=False)

    class Meta:
        table = "user"


class Cursor(Model):
    """Last known grid position for a player's cursor. `version` is stamped by a
    Postgres trigger on every write, turning the table into a change feed."""

    identity = CharField(max_length=100, pk=True)
    x = IntField()
    y = IntField()
    z = IntField()
    active = BooleanField(default=True)
    version = BigIntField(default=0)

    class Meta:
        table = "cursor"


class Event(Model):
    """Kill-feed entry. Trimmed to 40 rows after each insert."""

    id = IntField(pk=True)
    kind = CharField(max_length=50, description="EventKind variant name")
    identity = CharField(max_length=100, description="Session UUID of the actor")
    brick_id = IntField(null=True)
    timestamp = DatetimeField(auto_now_add=True)

    class Meta:
        table = "event"
        ordering = ["id"]
