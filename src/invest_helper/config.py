"""Application settings loaded from environment / .env."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
    )
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_timeout_seconds: float = Field(default=120.0, alias="OPENAI_TIMEOUT_SECONDS")
    moex_timeout_seconds: float = Field(default=30.0, alias="MOEX_TIMEOUT_SECONDS")
    system_prompt_path: str = Field(default="", alias="SYSTEM_PROMPT_PATH")

    def llm_configured(self) -> bool:
        return bool(self.openai_api_key.strip() and self.openai_model.strip())


def get_settings() -> Settings:
    return Settings()
