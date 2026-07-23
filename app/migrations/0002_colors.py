from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields


class Migration(migrations.Migration):
    dependencies = [("models", "0001_auto")]

    initial = False

    operations = [
        ops.AddField(
            model_name="Brick",
            name="color_seed",
            field=fields.IntField(null=True),
        ),
        ops.RunSQL(
            """
            UPDATE bricks
            SET color_seed = COALESCE(
                created_by_id,
                CASE color
                    WHEN 'cyan' THEN 1
                    WHEN 'purple' THEN 2
                    WHEN 'orange' THEN 3
                    WHEN 'green' THEN 4
                    WHEN 'pink' THEN 5
                    WHEN 'yellow' THEN 6
                END
            )
            """
        ),
        ops.AlterField(
            model_name="Brick",
            name="color_seed",
            field=fields.IntField(),
        ),
        ops.RemoveField(model_name="Brick", name="color"),
        ops.AlterModelOptions(
            name="Cursor",
            options={
                "table": "cursors",
                "app": "models",
                "pk_attr": "player_id",
                "table_description": "Last known grid position for a player's cursor.",
            },
        ),
        ops.RemoveField(model_name="Player", name="color"),
    ]
