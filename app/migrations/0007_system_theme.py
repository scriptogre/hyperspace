from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from app.enums import Theme


class Migration(migrations.Migration):
    dependencies = [("models", "0006_world")]

    initial = False

    operations = [
        ops.AlterField(
            model_name="World",
            name="theme",
            field=fields.CharEnumField(
                enum_type=Theme,
                max_length=5,
                null=True,
            ),
        ),
        ops.RunSQL(
            "UPDATE worlds SET theme = NULL WHERE theme = 'light'",
            "UPDATE worlds SET theme = 'light' WHERE theme IS NULL",
        ),
    ]
