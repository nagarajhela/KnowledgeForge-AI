import re
from dataclasses import dataclass

import tiktoken

from app.providers.extractors.base import ExtractedDocument


@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    content: str
    token_count: int
    page_number: int | None
    section_title: str | None


class ChunkingService:
    """Text normalization, lightweight language detection, and token-aware chunking."""

    def __init__(self) -> None:
        try:
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        return max(1, len(text.split()))

    @staticmethod
    def normalize_text(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def detect_language(text: str) -> str:
        sample = text[:1000].lower()
        if any(w in sample for w in (" the ", " and ", " is ", " for ", " with ")):
            return "en"
        if any(w in sample for w in (" der ", " die ", " und ", " ist ")):
            return "de"
        if any(w in sample for w in (" le ", " la ", " et ", " est ", " pour ")):
            return "fr"
        if any(w in sample for w in (" el ", " la ", " y ", " es ", " para ")):
            return "es"
        return "en"

    def chunk_document(
        self,
        extracted: ExtractedDocument,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        idx = 0
        safe_overlap = min(chunk_overlap, max(0, chunk_size // 2))

        for page in extracted.pages:
            normalized = self.normalize_text(page.text)
            if not normalized:
                continue

            if self._encoder is not None:
                tokens = self._encoder.encode(normalized)
                start = 0
                step = max(1, chunk_size - safe_overlap)
                while start < len(tokens):
                    window = tokens[start : start + chunk_size]
                    chunk_text = self._encoder.decode(window).strip()
                    if chunk_text:
                        chunks.append(
                            TextChunk(
                                chunk_index=idx,
                                content=chunk_text,
                                token_count=len(window),
                                page_number=page.page_number,
                                section_title=page.section_title,
                            )
                        )
                        idx += 1
                    if start + chunk_size >= len(tokens):
                        break
                    start += step
            else:
                words = normalized.split()
                start = 0
                step = max(1, chunk_size - safe_overlap)
                while start < len(words):
                    window = words[start : start + chunk_size]
                    chunk_text = " ".join(window).strip()
                    if chunk_text:
                        chunks.append(
                            TextChunk(
                                chunk_index=idx,
                                content=chunk_text,
                                token_count=len(window),
                                page_number=page.page_number,
                                section_title=page.section_title,
                            )
                        )
                        idx += 1
                    if start + chunk_size >= len(words):
                        break
                    start += step

        return chunks
