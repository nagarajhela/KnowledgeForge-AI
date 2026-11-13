import asyncio
import json
from collections.abc import AsyncIterator

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.config import settings
from app.providers.llm.base import LLMProvider, LLMResult


class OpenAILLMProvider(LLMProvider):
    provider_name = "openai"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key or settings.OPENAI_API_KEY,
            base_url=base_url or settings.OPENAI_BASE_URL,
        )

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> LLMResult:
        full_msgs = [{"role": "system", "content": system_prompt}, *messages]
        resp = await self.client.chat.completions.create(
            model=model,
            messages=full_msgs,  # type: ignore[arg-type]
            temperature=temperature,
        )
        choice = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMResult(
            content=choice,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=model,
            provider=self.provider_name,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        full_msgs = [{"role": "system", "content": system_prompt}, *messages]
        stream = await self.client.chat.completions.create(
            model=model,
            messages=full_msgs,  # type: ignore[arg-type]
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


class AzureOpenAILLMProvider(OpenAILLMProvider):
    provider_name = "azure_openai"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        self.client = AsyncAzureOpenAI(  # type: ignore[assignment]
            api_key=api_key or settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=base_url or settings.AZURE_OPENAI_ENDPOINT or "",
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )


class AnthropicLLMProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(self, *, api_key: str | None = None) -> None:
        self.client = AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> LLMResult:
        resp = await self.client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=2048,
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        return LLMResult(
            content=text,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            model=model,
            provider=self.provider_name,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        async with self.client.messages.stream(
            model=model,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=2048,
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OllamaLLMProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self, *, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> LLMResult:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = data.get("message", {}).get("content", "")
        return LLMResult(
            content=content,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            model=model,
            provider=self.provider_name,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    delta = data.get("message", {}).get("content")
                    if delta:
                        yield delta


class MockLocalLLMProvider(LLMProvider):
    """Grounded local fallback synthesizing answers exclusively from supplied context excerpts."""

    provider_name = "mock"

    @staticmethod
    def _synthesize(messages: list[dict[str, str]]) -> str:
        user_msg = messages[-1]["content"] if messages else ""
        if "[Source 1]" not in user_msg:
            return (
                "I do not have sufficient context in the authorized knowledge bases "
                "to answer this question reliably."
            )
        lines = [
            line.strip()
            for line in user_msg.splitlines()
            if line.strip() and not line.startswith("Question:") and not line.startswith("Context:")
        ]
        snippets = [ln for ln in lines if not ln.startswith("[Source")][:3]
        summary = " ".join(snippets)[:520].strip()
        return f"Based on the retrieved organization knowledge [Source 1]: {summary}"

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> LLMResult:
        answer = self._synthesize(messages)
        prompt_tokens = sum(len(m["content"].split()) for m in messages) + len(system_prompt.split())
        completion_tokens = len(answer.split())
        return LLMResult(
            content=answer,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
            provider=self.provider_name,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        answer = self._synthesize(messages)
        for word in answer.split(" "):
            yield word + " "
            await asyncio.sleep(0.01)


def get_llm_provider(
    provider_name: str | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    name = (provider_name or settings.DEFAULT_LLM_PROVIDER).lower()
    if name == "openai" and (api_key or settings.OPENAI_API_KEY):
        return OpenAILLMProvider(api_key=api_key, base_url=base_url)
    if name == "azure_openai" and (api_key or settings.AZURE_OPENAI_API_KEY):
        return AzureOpenAILLMProvider(api_key=api_key)
    if name == "anthropic" and (api_key or settings.ANTHROPIC_API_KEY):
        return AnthropicLLMProvider(api_key=api_key)
    if name == "ollama":
        return OllamaLLMProvider(base_url=base_url)
    return MockLocalLLMProvider()
