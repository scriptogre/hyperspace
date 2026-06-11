"""minijinja (Rust) template rendering. Named jinja.py by convention."""

from pathlib import Path

import minijinja

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = minijinja.Environment(
    loader=lambda name: (_TEMPLATES_DIR / name).read_text(),
    auto_escape_callback=lambda name: True,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Cache the one-line wrapper template generated per fragment so the hot path
# never recompiles it.
_fragments: set[str] = set()


def render(name: str, context: dict | None = None) -> str:
    """Render a template, or a single macro with `name#fragment` syntax.

    `render("index.html.j2")` renders the page; `render("index.html.j2#stage")`
    renders just the `stage` macro, which reads the same context.
    """
    context = context or {}

    if "#" not in name:
        return _env.render_template(name, **context)

    template, fragment = name.split("#", 1)
    key = f"__fragment__{template}#{fragment}"
    if key not in _fragments:
        _env.add_template(
            key,
            f'{{% from "{template}" import {fragment} with context %}}{{{{ {fragment}() }}}}',
        )
        _fragments.add(key)
    return _env.render_template(key, **context)
