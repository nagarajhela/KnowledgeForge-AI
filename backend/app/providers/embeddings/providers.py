import hashlib
import math
import re

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.config import settings
from app.providers.embeddings.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Supports OpenAI and OpenAI-compatible embedding endpoints."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or settings.DEFAULT_EMBEDDING_MODEL
        self.client = AsyncOpenAI(
            api_key=api_key or settings.OPENAI_API_KEY,
            base_url=base_url or settings.OPENAI_BASE_URL,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self.client.embeddings.create(model=self.model, input=texts)
        return [list(item.embedding) for item in resp.data]


class AzureOpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        deployment: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.deployment = deployment or settings.DEFAULT_EMBEDDING_MODEL
        self.client = AsyncAzureOpenAI(
            api_key=api_key or settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=base_url or settings.AZURE_OPENAI_ENDPOINT or "",
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self.client.embeddings.create(model=self.deployment, input=texts)
        return [list(item.embedding) for item in resp.data]


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or "nomic-embed-text"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                resp.raise_for_status()
                vectors.append(resp.json()["embedding"])
        return vectors


class MockLocalEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic feature-hashing embedding provider for local development & tests without API keys.
    Maps word tokens into normalized dense vectors so lexical overlap correlates with cosine similarity.
    """

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS

    def _embed_single(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9]{2,}", text.lower())
        if not tokens:
            vec[0] = 1.0
            return vec
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_single(t) for t in texts]


def get_embedding_provider(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> EmbeddingProvider:
    name = (provider_name or settings.DEFAULT_EMBEDDING_PROVIDER).lower()
    if name == "openai" and (api_key or settings.OPENAI_API_KEY):
        return OpenAIEmbeddingProvider(api_key=api_key, base_url=base_url, model=model)
    if name == "azure_openai" and (api_key or settings.AZURE_OPENAI_API_KEY):
        return AzureOpenAIEmbeddingProvider(api_key=api_key, deployment=model, base_url=base_url)
    if name == "ollama":
        return OllamaEmbeddingProvider(base_url=base_url, model=model)
    return MockLocalEmbeddingProvider()
