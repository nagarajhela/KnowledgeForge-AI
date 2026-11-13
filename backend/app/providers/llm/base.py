from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(slots=True)
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    provider: str


class LLMProvider(ABC):
    """Abstract LLM provider interface supporting non-streaming and token-streaming generation."""

    provider_name: str

    @abstractmethod
    async def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> LLMResult:
        """Generate a complete response."""

    @abstractmethod
    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """Yield generated text tokens incrementally."""
