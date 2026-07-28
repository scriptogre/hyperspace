"""minijinja (Rust) template rendering. Named jinja.py by convention."""

import minijinja

from app.config import settings


def url_for(name: str, **params: str) -> str:
    """Resolve a route name to its path. Deferred import breaks the cycle: routes imports jinja."""
    from app.main import app

    return minijinja.safe(str(app.url_path_for(name, **params)))


_env = minijinja.Environment(
    loader=lambda name: (settings.TEMPLATES_DIR / name).read_text(),
    auto_escape_callback=lambda name: True,
    globals={"url_for": url_for},
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(name: str, context: dict | None = None) -> str:
    """
    Render template by name with given context.
    """
    return _env.render_template(name, **(context or {}))
