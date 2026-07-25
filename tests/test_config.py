import pytest

from app.config import Settings


@pytest.fixture
def settings_kwargs() -> dict:
    return {
        "_env_file": None,
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": 5432,
        "POSTGRES_USER": "hyperspace",
        "POSTGRES_PASSWORD": "hyperspace",
        "POSTGRES_DB": "hyperspace",
    }


@pytest.mark.parametrize(
    ("environment", "domain", "expected"),
    [
        ("local", None, "http://localhost:8000"),
        ("testing", None, "http://localhost:8000"),
        ("production", None, "https://hyperspace.christiantanul.com"),
        ("local", "192.168.1.23:8000", "http://192.168.1.23:8000"),
        ("production", "hyperspace.example.com", "https://hyperspace.example.com"),
        ("production", "http://192.168.1.23:8000/", "http://192.168.1.23:8000"),
    ],
)
def test_join_url(settings_kwargs, environment, domain, expected):
    settings = Settings(
        **settings_kwargs,
        ENVIRONMENT=environment,
        DOMAIN=domain,
    )

    assert settings.JOIN_URL == expected
