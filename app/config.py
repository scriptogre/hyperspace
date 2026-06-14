"""Application settings."""

from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
    )

    # Application
    # --------------------
    ENVIRONMENT: Literal["local", "production"] = "local"
    DEBUG: bool = True
    WEB_CONCURRENCY: int = 4
    SECRET_KEY: str = "dev-insecure-change-me"  # signs the form-errors cookie

    # Directories
    # --------------------
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STATIC_DIR: Path = BASE_DIR / "app" / "static"
    TEMPLATES_DIR: Path = BASE_DIR / "app" / "templates"

    # Database
    # --------------------
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field
    @property
    def TORTOISE_ORM(self) -> dict:
        return {
            "connections": {
                "default": {
                    "engine": "tortoise.backends.asyncpg",
                    "credentials": {
                        "host": self.POSTGRES_HOST,
                        "port": self.POSTGRES_PORT,
                        "user": self.POSTGRES_USER,
                        "password": self.POSTGRES_PASSWORD,
                        "database": self.POSTGRES_DB,
                        "minsize": 5,
                        "maxsize": 20,
                    },
                }
            },
            "apps": {
                "models": {
                    "models": ["app.models"],
                    "default_connection": "default",
                }
            },
        }


settings = Settings()  # type: ignore[call-arg]

TORTOISE_ORM = settings.TORTOISE_ORM  # top-level alias for tortoise CLI
