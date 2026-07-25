from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0009_database_world_shrink")]

    initial = False

    operations = [
        ops.DeleteModel(name="Event"),
    ]
