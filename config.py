"""Environment-backed application configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Resolved settings used by the CLI and LLM adapter."""

    provider: str
    model: str
    anthropic_api_key: str | None
    openai_api_key: str | None
    ollama_base_url: str
    request_timeout_seconds: float = 120.0


SUPPORTED_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "ollama")


def load_settings(
    provider_override: str | None = None,
    model_override: str | None = None,
    env_file: str | Path | None = None,
) -> Settings:
    """Load provider configuration from environment variables and optional overrides."""

    load_dotenv(dotenv_path=env_file)
    provider = (provider_override or os.getenv("LLM_PROVIDER", "anthropic")).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigurationError(f"Unsupported LLM_PROVIDER '{provider}'. Choose: {supported}.")

    model = (model_override or os.getenv("LLM_MODEL", "claude-sonnet-4-6")).strip()
    if not model:
        raise ConfigurationError("LLM_MODEL must not be empty.")

    timeout_value = os.getenv("LLM_TIMEOUT_SECONDS", "120")
    try:
        timeout = float(timeout_value)
    except ValueError as exc:
        raise ConfigurationError("LLM_TIMEOUT_SECONDS must be a number.") from exc
    if timeout <= 0:
        raise ConfigurationError("LLM_TIMEOUT_SECONDS must be greater than zero.")

    return Settings(
        provider=provider,
        model=model,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        request_timeout_seconds=timeout,
    )
