"""minijinja (Rust) template rendering. Named jinja.py by convention."""

import minijinja

from app.config import settings
from app.enums import Color

GRID_SIZE = 12

_env = minijinja.Environment(
    loader=lambda name: (settings.TEMPLATES_DIR / name).read_text(),
    auto_escape_callback=lambda name: True,
    globals={"Color": Color, "grid_size": GRID_SIZE},
)


def render(name: str, context: dict | None = None) -> str:
    """
    Render template by name with given context.
    """
    return _env.render_template(name, **(context or {}))
