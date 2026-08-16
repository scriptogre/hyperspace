import pytest

from app import dependencies
from app.exceptions import FormErrors
from tests import run_async


@pytest.mark.parametrize(
    ("data", "expected"), [({}, "Jamie"), ({"name": "Chris"}, "Chris")]
)
def test_game_context_supplies_a_player_name(monkeypatch, data, expected):
    monkeypatch.setattr(dependencies, "choice", lambda names: names[6])

    context = run_async(
        dependencies.get_game_context({}, [], None, FormErrors(data=data))
    )

    assert context["suggested_name"] == expected
