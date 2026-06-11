"""minijinja (Rust) template rendering. Named jinja.py by convention."""

from pathlib import Path

import minijinja

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = minijinja.Environment(
    loader=lambda name: (_TEMPLATES_DIR / name).read_text(),
    auto_escape_callback=lambda name: True,
)


def render(name: str, context: dict | None = None) -> str:
    """Render a template by name with the given context."""
    return _env.render_template(name, **(context or {}))
