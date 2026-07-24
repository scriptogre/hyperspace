from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from app.enums import Theme


class Migration(migrations.Migration):
    dependencies = [("models", "0005_notifications")]

    initial = False

    operations = [
        ops.CreateModel(
            name="World",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=False,
                        primary_key=True,
                        default=1,
                        unique=True,
                        db_index=True,
                    ),
                ),
                (
                    "theme",
                    fields.CharEnumField(
                        enum_type=Theme,
                        max_length=5,
                        default=Theme.LIGHT,
                    ),
                ),
                ("size", fields.IntField(default=12)),
                ("announcement", fields.TextField(null=True)),
            ],
            options={
                "table": "worlds",
                "app": "models",
                "pk_attr": "id",
                "table_description": "The singleton world configuration.",
            },
            bases=["Model"],
        ),
        ops.RunSQL(
            """
            INSERT INTO worlds (id, theme, size, announcement)
            VALUES (1, 'light', 12, NULL);

            ALTER TABLE worlds
              ADD CONSTRAINT worlds_singleton CHECK (id = 1),
              ADD CONSTRAINT worlds_theme CHECK (theme IN ('light', 'dark')),
              ADD CONSTRAINT worlds_size CHECK (size BETWEEN 1 AND 32);

            CREATE OR REPLACE FUNCTION hyperspace_protect_world()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION
                'the world singleton cannot be deleted or truncated';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER worlds_protect
              BEFORE DELETE OR TRUNCATE ON worlds
              FOR EACH STATEMENT
              EXECUTE FUNCTION hyperspace_protect_world();

            CREATE OR REPLACE FUNCTION hyperspace_validate_world_resize()
            RETURNS trigger AS $$
            BEGIN
              IF NEW.size < OLD.size AND (
                EXISTS (
                  SELECT 1
                    FROM bricks
                   WHERE x >= NEW.size
                      OR y >= NEW.size
                      OR z >= NEW.size
                )
                OR EXISTS (
                  SELECT 1
                    FROM cursors
                   WHERE x >= NEW.size
                      OR y >= NEW.size
                )
              ) THEN
                RAISE EXCEPTION
                  'cannot shrink world below existing coordinates';
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER worlds_validate_resize
              BEFORE UPDATE OF size ON worlds
              FOR EACH ROW
              EXECUTE FUNCTION hyperspace_validate_world_resize();

            CREATE OR REPLACE FUNCTION hyperspace_validate_brick()
            RETURNS trigger AS $$
            DECLARE
              world_size integer;
            BEGIN
              SELECT size
                INTO world_size
                FROM worlds
               WHERE id = 1
               FOR SHARE;

              IF world_size IS NULL
                 OR NEW.x < 0
                 OR NEW.y < 0
                 OR NEW.z < 0
                 OR NEW.x >= world_size
                 OR NEW.y >= world_size
                 OR NEW.z >= world_size THEN
                RAISE EXCEPTION
                  'brick coordinate is outside the world';
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER bricks_validate_coordinate
              BEFORE INSERT OR UPDATE OF x, y, z ON bricks
              FOR EACH ROW
              EXECUTE FUNCTION hyperspace_validate_brick();

            CREATE OR REPLACE FUNCTION hyperspace_validate_cursor()
            RETURNS trigger AS $$
            DECLARE
              world_size integer;
            BEGIN
              SELECT size
                INTO world_size
                FROM worlds
               WHERE id = 1
               FOR SHARE;

              IF world_size IS NULL
                 OR NEW.x < 0
                 OR NEW.y < 0
                 OR NEW.x >= world_size
                 OR NEW.y >= world_size THEN
                RAISE EXCEPTION
                  'cursor coordinate is outside the world';
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER cursors_validate_coordinate
              BEFORE INSERT OR UPDATE OF x, y ON cursors
              FOR EACH ROW
              EXECUTE FUNCTION hyperspace_validate_cursor();

            CREATE OR REPLACE FUNCTION hyperspace_notify()
            RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify('hyperspace', 'world_changed');
              RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS events_notify ON events;

            DROP TRIGGER IF EXISTS bricks_notify ON bricks;
            CREATE TRIGGER bricks_notify
              AFTER INSERT OR UPDATE OR DELETE ON bricks
              FOR EACH STATEMENT
              EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS players_notify ON players;
            CREATE TRIGGER players_notify
              AFTER INSERT OR UPDATE OR DELETE ON players
              FOR EACH STATEMENT
              EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS cursors_notify ON cursors;
            CREATE TRIGGER cursors_notify
              AFTER INSERT OR UPDATE OR DELETE ON cursors
              FOR EACH STATEMENT
              EXECUTE FUNCTION hyperspace_notify();

            DROP TRIGGER IF EXISTS worlds_notify ON worlds;
            CREATE TRIGGER worlds_notify
              AFTER INSERT OR UPDATE OR DELETE ON worlds
              FOR EACH STATEMENT
              EXECUTE FUNCTION hyperspace_notify();
            """,
            """
            DROP TRIGGER IF EXISTS worlds_notify ON worlds;
            DROP TRIGGER IF EXISTS bricks_notify ON bricks;
            DROP TRIGGER IF EXISTS players_notify ON players;
            DROP TRIGGER IF EXISTS cursors_notify ON cursors;
            DROP TRIGGER IF EXISTS events_notify ON events;

            DROP FUNCTION IF EXISTS hyperspace_notify();

            DROP TRIGGER IF EXISTS cursors_validate_coordinate ON cursors;
            DROP TRIGGER IF EXISTS bricks_validate_coordinate ON bricks;
            DROP TRIGGER IF EXISTS worlds_validate_resize ON worlds;
            DROP TRIGGER IF EXISTS worlds_protect ON worlds;

            DROP FUNCTION IF EXISTS hyperspace_validate_cursor();
            DROP FUNCTION IF EXISTS hyperspace_validate_brick();
            DROP FUNCTION IF EXISTS hyperspace_validate_world_resize();
            DROP FUNCTION IF EXISTS hyperspace_protect_world();

            DROP TABLE IF EXISTS worlds;
            """,
        ),
    ]
