from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0007_system_theme")]

    initial = False

    operations = [
        ops.RunSQL(
            """
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
                RAISE EXCEPTION USING
                  MESSAGE = 'brick coordinate is outside the world',
                  ERRCODE = '23514',
                  CONSTRAINT = 'bricks_world_bounds';
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

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
                RAISE EXCEPTION USING
                  MESSAGE = 'cursor coordinate is outside the world',
                  ERRCODE = '23514',
                  CONSTRAINT = 'cursors_world_bounds';
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
            """
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
            """,
        )
    ]
