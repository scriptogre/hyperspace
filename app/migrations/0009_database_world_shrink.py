from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0008_coordinate_constraints")]

    initial = False

    operations = [
        ops.RunSQL(
            """
            CREATE OR REPLACE FUNCTION hyperspace_validate_world_resize()
            RETURNS trigger AS $$
            BEGIN
              IF NEW.size < OLD.size THEN
                DELETE FROM bricks
                 WHERE x >= NEW.size
                    OR y >= NEW.size
                    OR z >= NEW.size;

                DELETE FROM cursors
                 WHERE x >= NEW.size
                    OR y >= NEW.size;
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
            """
            CREATE OR REPLACE FUNCTION hyperspace_validate_world_resize()
            RETURNS trigger AS $$
            BEGIN
              IF NEW.size < OLD.size THEN
                IF EXISTS (
                  SELECT 1
                    FROM bricks
                   WHERE x >= NEW.size
                      OR y >= NEW.size
                      OR z >= NEW.size
                ) THEN
                  RAISE EXCEPTION
                    'cannot shrink world below existing bricks';
                END IF;

                DELETE FROM cursors
                 WHERE x >= NEW.size
                    OR y >= NEW.size;
              END IF;

              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
    ]
