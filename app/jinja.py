"""minijinja (Rust) template rendering. Named jinja.py by convention."""

import minijinja

from app.config import settings

_env = minijinja.Environment(
    loader=lambda name: (settings.TEMPLATES_DIR / name).read_text(),
    auto_escape_callback=lambda name: True,
)


def render(name: str, context: dict | None = None) -> str:
    """Render a template by name with the given context."""
    return _env.render_template(name, **(context or {}))
