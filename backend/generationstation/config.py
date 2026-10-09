from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GS_", env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )
    database_url: SecretStr
    api_token: SecretStr
    host_role: Literal["development", "desktop"] = "development"
    host_label: str = Field(default="Development machine", min_length=1, max_length=120)
    allowed_origins: list[str] = []
    sample_interval_seconds: float = Field(default=1, ge=0.2, le=10)
    stale_after_seconds: float = Field(default=5, ge=2, le=60)

    @model_validator(mode="after")
    def stale_window_exceeds_sample_interval(self):
        if self.stale_after_seconds <= self.sample_interval_seconds:
            raise ValueError("stale_after_seconds must exceed sample_interval_seconds")
        return self

    @field_validator("api_token")
    @classmethod
    def strong_token(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 32 or raw.startswith("replace-") or not raw.isascii():
            raise ValueError("Generate an ASCII API token of at least 32 characters with scripts/init_env.py")
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        if make_url(value.get_secret_value()).drivername != "postgresql+psycopg":
            raise ValueError("Use a postgresql+psycopg database URL")
        return value
