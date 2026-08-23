import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required environment variables are absent."""


@dataclass(frozen=True)
class Settings:
    uri: str
    user: str
    password: str
    database: str | None
    app_name: str

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("COGNODB_URI", self.uri),
                ("COGNODB_USER", self.user),
                ("COGNODB_PASSWORD", self.password),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                "Missing environment variable(s): "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill in your CognoDB details."
            )


def load_settings() -> Settings:
    database = os.getenv("COGNODB_DATABASE", "").strip()
    return Settings(
        uri=os.getenv("COGNODB_URI", "").strip(),
        user=os.getenv("COGNODB_USER", "cognodb").strip(),
        password=os.getenv("COGNODB_PASSWORD", "").strip(),
        database=database or None,
        app_name=os.getenv("APP_NAME", "Ownership Lens").strip(),
    )


settings = load_settings()