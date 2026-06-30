from tortoise import migrations
from tortoise.migrations import operations as ops
from app.enums import Color, EventType
from tortoise.fields.base import OnDelete
from tortoise import fields


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="Player",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "token",
                    fields.CharField(
                        unique=True, description="UUID from the cookie", max_length=64
                    ),
                ),
                ("name", fields.CharField(max_length=100)),
                (
                    "color",
                    fields.CharEnumField(
                        description="CYAN: cyan\nPURPLE: purple\nORANGE: orange\nGREEN: green\nPINK: pink\nYELLOW: yellow",
                        enum_type=Color,
                        max_length=20,
                    ),
                ),
                ("is_online", fields.BooleanField(default=False)),
            ],
            options={
                "table": "players",
                "app": "models",
                "pk_attr": "id",
                "table_description": "A player in the game.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Brick",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("x", fields.IntField()),
                ("y", fields.IntField()),
                ("z", fields.IntField()),
                (
                    "color",
                    fields.CharEnumField(
                        description="CYAN: cyan\nPURPLE: purple\nORANGE: orange\nGREEN: green\nPINK: pink\nYELLOW: yellow",
                        enum_type=Color,
                        max_length=20,
                    ),
                ),
                (
                    "created_by",
                    fields.ForeignKeyField(
                        "models.Player",
                        source_field="created_by_id",
                        null=True,
                        description="player who created this brick",
                        db_constraint=True,
                        to_field="id",
                        related_name="bricks",
                        on_delete=OnDelete.SET_NULL,
                    ),
                ),
                (
                    "dragged_by",
                    fields.ForeignKeyField(
                        "models.Player",
                        source_field="dragged_by_id",
                        null=True,
                        description="player currently dragging this brick",
                        db_constraint=True,
                        to_field="id",
                        related_name="dragged_brick",
                        on_delete=OnDelete.SET_NULL,
                    ),
                ),
            ],
            options={
                "table": "bricks",
                "app": "models",
                "pk_attr": "id",
                "table_description": "A colored block placed on the isometric grid.",
            },
            bases=["Model"],
        ),
        ops.AddIndex("Brick", ops.Index(fields=["x", "y", "z"])),
        ops.CreateModel(
            name="Cursor",
            fields=[
                ("x", fields.IntField()),
                ("y", fields.IntField()),
                ("z", fields.IntField()),
                ("version", fields.BigIntField(default=0)),
                (
                    "player",
                    fields.OneToOneField(
                        "models.Player",
                        source_field="player_id",
                        primary_key=True,
                        db_index=True,
                        db_constraint=True,
                        to_field="id",
                        related_name="cursor",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
            ],
            options={
                "table": "cursors",
                "app": "models",
                "pk_attr": "player_id",
                "table_description": "Last known grid position for a player's cursor.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Event",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "type",
                    fields.CharEnumField(
                        description="PLAYER_JOINED: player_joined\nPLAYER_LEFT: player_left\nBRICK_CREATED: brick_created\nBRICK_DELETED: brick_deleted\nDRAG_STARTED: drag_started\nDRAG_ENDED: drag_ended",
                        enum_type=EventType,
                        max_length=50,
                    ),
                ),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                (
                    "player",
                    fields.ForeignKeyField(
                        "models.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="events",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "brick",
                    fields.ForeignKeyField(
                        "models.Brick",
                        source_field="brick_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        related_name="events",
                        on_delete=OnDelete.SET_NULL,
                    ),
                ),
            ],
            options={
                "table": "events",
                "app": "models",
                "pk_attr": "id",
                "table_description": "An entry in the activity feed.",
            },
            bases=["Model"],
        ),
    ]
