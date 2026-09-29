"""Provider-swappable BYOK adapters for LLM generation."""

from abc import ABC, abstractmethod
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import ConfigurationError, Settings
from models.llm_result import LLMResult

class LLMError(RuntimeError):
    """Raised when an LLM provider cannot generate a response."""


class LLMAdapter(ABC):
    """Interface implemented by every supported LLM provider."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a text response for a prompt."""

    def generate_result(self, prompt: str) -> LLMResult:
        """Return a result object while preserving legacy adapter subclasses."""

        return LLMResult(text=self.generate(prompt), model=getattr(self, "_model", ""))


class AnthropicAdapter(LLMAdapter):
    """Adapter for the Anthropic Messages API."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the adapter after validating the Anthropic key."""

        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic.")
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ConfigurationError("The anthropic package is required for the Anthropic provider.") from exc
        self._client = Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.request_timeout_seconds,
        )
        self._model = settings.model

    def generate(self, prompt: str) -> str:
        """Generate text using Anthropic without exposing the API key."""

        return self.generate_result(prompt).text

    def generate_result(self, prompt: str) -> LLMResult:
        """Generate text and map available Anthropic metadata."""

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
            )
            content = getattr(response, "content", [])
            text_parts = [getattr(block, "text", "") for block in content]
            result = "".join(part for part in text_parts if part)
        except Exception as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        if not result.strip():
            raise LLMError("Anthropic returned an empty response.")
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=result,
            model=_field(response, "model") or self._model,
            finish_reason=_field(response, "stop_reason"),
            input_tokens=_field(usage, "input_tokens"),
            output_tokens=_field(usage, "output_tokens"),
        )


import os
import uuid

class OpenAIAdapter(LLMAdapter):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ConfigurationError("The openai package is required for the OpenAI provider.") from exc
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=os.environ.get("OPENAI_BASE_URL", "https://opencode.ai/zen/go/v1"),
            timeout=settings.request_timeout_seconds,
            default_headers={
                "x-opencode-session": str(uuid.uuid4())
            }
        )
        self._model = settings.model

    def generate(self, prompt: str) -> str:
        """Generate text using OpenAI without exposing the API key."""

        return self.generate_result(prompt).text

    def generate_result(self, prompt: str) -> LLMResult:
        """Generate text and map optional OpenAI-compatible metadata."""

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            choice = response.choices[0]
            result = choice.message.content or ""
        except Exception as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc
        if not result.strip():
            raise LLMError("OpenAI returned an empty response.")
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=result,
            model=_field(response, "model") or self._model,
            finish_reason=_field(choice, "finish_reason"),
            input_tokens=_field(usage, "prompt_tokens"),
            output_tokens=_field(usage, "completion_tokens"),
        )


class OllamaAdapter(LLMAdapter):
    """Adapter for a local Ollama HTTP server."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the adapter with the configured local Ollama endpoint."""

        self._base_url = settings.ollama_base_url
        self._model = settings.model
        self._timeout = settings.request_timeout_seconds

    def generate(self, prompt: str) -> str:
        """Generate text through Ollama's local `/api/generate` endpoint."""

        return self.generate_result(prompt).text

    def generate_result(self, prompt: str) -> LLMResult:
        """Generate text and map Ollama metadata when present."""

        payload = json.dumps({"model": self._model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = Request(
            f"{self._base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = response.read().decode("utf-8")
            decoded: Any = json.loads(body)
            result = decoded.get("response", "")
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        if not isinstance(result, str) or not result.strip():
            raise LLMError("Ollama returned an empty response.")
        return LLMResult(
            text=result,
            model=decoded.get("model") or self._model,
            finish_reason=decoded.get("done_reason"),
            input_tokens=decoded.get("prompt_eval_count"),
            output_tokens=decoded.get("eval_count"),
        )


def create_adapter(settings: Settings) -> LLMAdapter:
    """Create the configured provider adapter without changing other layers."""

    adapters: dict[str, type[LLMAdapter]] = {
        "anthropic": AnthropicAdapter,
        "openai": OpenAIAdapter,
        "ollama": OllamaAdapter,
    }
    adapter_type = adapters.get(settings.provider)
    if adapter_type is None:
        raise ConfigurationError(f"Unsupported LLM provider '{settings.provider}'.")
    return adapter_type(settings)


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read provider metadata from SDK objects or test-friendly mappings."""

    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
