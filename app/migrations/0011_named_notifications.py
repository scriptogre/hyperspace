from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0010_drop_events")]

    initial = False

    operations = [
        ops.RunSQL(
            """
            CREATE OR REPLACE FUNCTION hyperspace_notify()
            RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify(
                'hyperspace',
                TG_TABLE_NAME || '_changed'
              );
              RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            """,
            """
            CREATE OR REPLACE FUNCTION hyperspace_notify()
            RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify('hyperspace', 'world_changed');
              RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
    ]
