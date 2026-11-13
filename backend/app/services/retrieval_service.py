import math
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DocumentStatus
from app.models.knowledge import Document, DocumentChunk
from app.services.chunking_service import ChunkingService


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    document_name: str
    content: str
    page_number: int | None
    source_url: str | None
    vector_score: float
    fts_score: float
    relevance_score: float
    token_count: int


class RerankerInterface(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[RetrievedChunk], *, top_k: int
    ) -> list[RetrievedChunk]:
        """Re-score and order candidate chunks by query relevance."""


class LexicalCrossReranker(RerankerInterface):
    """Lightweight deterministic reranker boosting exact query term and bigram matches."""

    async def rerank(
        self, query: str, candidates: list[RetrievedChunk], *, top_k: int
    ) -> list[RetrievedChunk]:
        q_tokens = set(re.findall(r"[a-z0-9]{2,}", query.lower()))
        for item in candidates:
            c_tokens = set(re.findall(r"[a-z0-9]{2,}", item.content.lower()))
            overlap = len(q_tokens & c_tokens) / max(1, len(q_tokens))
            exact_phrase_bonus = 0.15 if query.lower().strip() in item.content.lower() else 0.0
            item.relevance_score = round(
                min(1.0, (0.65 * item.relevance_score) + (0.35 * overlap) + exact_phrase_bonus),
                4,
            )
        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates[:top_k]


class RetrievalService:
    """
    Hybrid pgvector + PostgreSQL Full-Text retrieval strictly isolated by organization_id
    and authorized knowledge_base_ids.
    """

    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id
        self.reranker = LexicalCrossReranker()
        self.chunker = ChunkingService()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (na * nb)))

    async def hybrid_search(
        self,
        *,
        query: str,
        query_vector: list[float],
        knowledge_base_ids: list[uuid.UUID],
        top_k: int = 6,
        alpha: float = 0.65,
        rerank: bool = True,
        metadata_filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        if not knowledge_base_ids:
            return []

        is_pg = bool(self.db.bind and self.db.bind.dialect.name == "postgresql")
        candidate_limit = max(top_k * 4, 24)

        if is_pg:
            dist_expr = DocumentChunk.embedding.cosine_distance(query_vector)
            ts_query = func.plainto_tsquery("english", query)
            fts_expr = func.coalesce(func.ts_rank_cd(DocumentChunk.search_vector, ts_query), 0.0)
            stmt = (
                select(
                    DocumentChunk,
                    Document.filename,
                    Document.source_url,
                    (1.0 - dist_expr).label("vec_score"),
                    fts_expr.label("fts_score"),
                )
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.organization_id == self.organization_id,
                    Document.organization_id == self.organization_id,
                    DocumentChunk.knowledge_base_id.in_(knowledge_base_ids),
                    Document.deleted_at.is_(None),
                    Document.processing_status == DocumentStatus.COMPLETED,
                )
                .order_by(dist_expr.asc())
                .limit(candidate_limit)
            )
            rows = (await self.db.execute(stmt)).all()
            candidates: list[RetrievedChunk] = []
            for chunk, filename, source_url, vec_score, fts_score in rows:
                if not self._matches_metadata(chunk.metadata_json, metadata_filters):
                    continue
                v_score = max(0.0, min(1.0, float(vec_score or 0.0)))
                f_score = max(0.0, min(1.0, float(fts_score or 0.0)))
                combined = round((alpha * v_score) + ((1.0 - alpha) * f_score), 4)
                candidates.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        knowledge_base_id=chunk.knowledge_base_id,
                        document_name=filename,
                        content=chunk.content,
                        page_number=chunk.page_number,
                        source_url=source_url,
                        vector_score=v_score,
                        fts_score=f_score,
                        relevance_score=combined,
                        token_count=chunk.token_count,
                    )
                )
        else:
            stmt = (
                select(DocumentChunk, Document.filename, Document.source_url)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.organization_id == self.organization_id,
                    Document.organization_id == self.organization_id,
                    DocumentChunk.knowledge_base_id.in_(knowledge_base_ids),
                    Document.deleted_at.is_(None),
                    Document.processing_status == DocumentStatus.COMPLETED,
                )
            )
            rows = (await self.db.execute(stmt)).all()
            q_terms = set(re.findall(r"[a-z0-9]{2,}", query.lower()))
            candidates = []
            for chunk, filename, source_url in rows:
                if not self._matches_metadata(chunk.metadata_json, metadata_filters):
                    continue
                v_score = self._cosine_similarity(query_vector, chunk.embedding or [])
                c_terms = set(re.findall(r"[a-z0-9]{2,}", chunk.content.lower()))
                f_score = len(q_terms & c_terms) / max(1, len(q_terms))
                combined = round((alpha * v_score) + ((1.0 - alpha) * f_score), 4)
                candidates.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        knowledge_base_id=chunk.knowledge_base_id,
                        document_name=filename,
                        content=chunk.content,
                        page_number=chunk.page_number,
                        source_url=source_url,
                        vector_score=round(v_score, 4),
                        fts_score=round(f_score, 4),
                        relevance_score=combined,
                        token_count=chunk.token_count,
                    )
                )
            candidates.sort(key=lambda c: c.relevance_score, reverse=True)
            candidates = candidates[:candidate_limit]

        if rerank and candidates:
            return await self.reranker.rerank(query, candidates, top_k=top_k)
        return candidates[:top_k]

    @staticmethod
    def _matches_metadata(metadata: dict, filters: dict[str, str] | None) -> bool:
        if not filters:
            return True
        return all(str(metadata.get(k, "")).lower() == str(v).lower() for k, v in filters.items())

    def build_context_window(
        self, chunks: list[RetrievedChunk], *, max_context_tokens: int = 3000
    ) -> tuple[str, list[RetrievedChunk]]:
        selected: list[RetrievedChunk] = []
        blocks: list[str] = []
        used_tokens = 0
        for idx, chunk in enumerate(chunks, start=1):
            t_count = chunk.token_count or self.chunker.count_tokens(chunk.content)
            if used_tokens + t_count > max_context_tokens and selected:
                break
            page_info = f" (Page {chunk.page_number})" if chunk.page_number else ""
            blocks.append(
                f"[Source {idx}] {chunk.document_name}{page_info} [score={chunk.relevance_score:.2f}]\n"
                f"{chunk.content}"
            )
            selected.append(chunk)
            used_tokens += t_count
        return "\n\n---\n\n".join(blocks), selected
