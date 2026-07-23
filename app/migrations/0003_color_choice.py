from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields


class Migration(migrations.Migration):
    dependencies = [("models", "0002_colors")]

    initial = False

    operations = [
        ops.AddField(
            model_name="Player",
            name="color_seed",
            field=fields.IntField(null=True),
        ),
        ops.RunSQL("UPDATE players SET color_seed = id"),
        ops.AlterField(
            model_name="Player",
            name="color_seed",
            field=fields.IntField(),
        ),
    ]
