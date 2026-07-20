from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0003_color_choice")]

    initial = False

    operations = [
        ops.RunSQL(
            """
            UPDATE bricks
            SET color_seed = players.color_seed
            FROM players
            WHERE bricks.created_by_id = players.id
            """,
            """
            UPDATE bricks
            SET color_seed = created_by_id
            WHERE created_by_id IS NOT NULL
            """,
        ),
    ]
