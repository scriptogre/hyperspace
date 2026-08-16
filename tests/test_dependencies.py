from app import dependencies
from app.exceptions import FormErrors
from tests import run_async


def test_game_context_suggests_a_friendly_player_name(monkeypatch):
    monkeypatch.setattr(dependencies, "choice", lambda names: names[6])

    context = run_async(dependencies.get_game_context({}, [], None, FormErrors()))

    assert context["suggested_name"] == "Jamie"


def test_game_context_preserves_a_submitted_player_name(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "suggest_player_name",
        lambda: (_ for _ in ()).throw(AssertionError("should not generate a name")),
    )

    context = run_async(
        dependencies.get_game_context({}, [], None, FormErrors(data={"name": "Chris"}))
    )

    assert context["suggested_name"] == "Chris"
