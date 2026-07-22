from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0004_brick_player_colors")]

    initial = False

    operations = [
        ops.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_stat_statements",
            # Preserve an extension that may predate this app.
            ops.RunSQL.noop,
        ),
        ops.RunSQL(
            """
            CREATE OR REPLACE FUNCTION hyperspace_notify() RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify('hyperspace', TG_TABLE_NAME);
              RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS bricks_notify ON bricks;
            CREATE TRIGGER bricks_notify
              AFTER INSERT OR UPDATE OR DELETE ON bricks
              FOR EACH STATEMENT EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS players_notify ON players;
            CREATE TRIGGER players_notify
              AFTER INSERT OR UPDATE OR DELETE ON players
              FOR EACH STATEMENT EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS cursors_notify ON cursors;
            CREATE TRIGGER cursors_notify
              AFTER INSERT OR UPDATE OR DELETE ON cursors
              FOR EACH STATEMENT EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS events_notify ON events;
            CREATE TRIGGER events_notify
              AFTER INSERT OR UPDATE OR DELETE ON events
              FOR EACH STATEMENT EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS cursors_version ON cursors;
            """,
            """
            DROP TRIGGER IF EXISTS bricks_notify ON bricks;
            DROP TRIGGER IF EXISTS players_notify ON players;
            DROP TRIGGER IF EXISTS cursors_notify ON cursors;
            DROP TRIGGER IF EXISTS events_notify ON events;
            DROP FUNCTION IF EXISTS hyperspace_notify();
            """,
        ),
    ]
