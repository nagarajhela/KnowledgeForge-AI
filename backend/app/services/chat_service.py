import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.chat import ChatMessage, ChatSession, Feedback, MessageCitation
from app.models.enums import MessageRole, OrganizationRole
from app.models.user import User
from app.repositories.chat_repo import ChatMessageRepository, ChatSessionRepository
from app.schemas.chat import (
    ChatAnswerResponse,
    ChatAskRequest,
    ChatSessionCreateRequest,
    ChatSessionUpdateRequest,
    CitationResponse,
    FeedbackCreateRequest,
)
from app.services.billing_service import BillingService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievedChunk


class ChatService:
    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id
        self.session_repo = ChatSessionRepository(db, organization_id)
        self.message_repo = ChatMessageRepository(db, organization_id)
        self.kb_service = KnowledgeBaseService(db, organization_id)
        self.rag_service = RAGService(db, organization_id)
        self.billing = BillingService(db)

    async def create_session(
        self, user: User, role: OrganizationRole, payload: ChatSessionCreateRequest
    ) -> ChatSession:
        await self.kb_service.validate_requested_kbs(
            payload.knowledge_base_ids, user=user, role=role
        )
        session = ChatSession(
            organization_id=self.organization_id,
            user_id=user.id,
            title=payload.title.strip(),
            knowledge_base_ids=[str(k) for k in payload.knowledge_base_ids],
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def list_sessions(
        self, user: User, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[ChatSession], int]:
        return await self.session_repo.list_user_sessions(user.id, offset=offset, limit=limit)

    async def get_session(self, session_id: uuid.UUID, user: User) -> ChatSession:
        session = await self.session_repo.get_user_session(session_id, user.id)
        if not session:
            raise NotFoundError("Chat session not found")
        return session

    async def rename_session(
        self, session_id: uuid.UUID, user: User, payload: ChatSessionUpdateRequest
    ) -> ChatSession:
        session = await self.get_session(session_id, user)
        session.title = payload.title.strip()
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def delete_session(self, session_id: uuid.UUID, user: User) -> None:
        session = await self.get_session(session_id, user)
        session.deleted_at = datetime.now(UTC)
        await self.db.commit()

    async def list_messages(self, session_id: uuid.UUID, user: User) -> list[ChatMessage]:
        await self.get_session(session_id, user)
        return await self.message_repo.list_session_messages(session_id)

    async def ask(
        self,
        *,
        session_id: uuid.UUID,
        user: User,
        role: OrganizationRole,
        payload: ChatAskRequest,
    ) -> ChatAnswerResponse:
        await self.billing.assert_can_run_chat(self.organization_id)
        session = await self.get_session(session_id, user)
        kb_ids = payload.knowledge_base_ids or [uuid.UUID(k) for k in session.knowledge_base_ids]
        kbs = await self.kb_service.validate_requested_kbs(kb_ids, user=user, role=role)

        history_rows = await self.message_repo.list_session_messages(session.id)
        history = [{"role": m.role.value, "content": m.content} for m in history_rows]

        user_msg = ChatMessage(
            organization_id=self.organization_id,
            session_id=session.id,
            user_id=user.id,
            role=MessageRole.USER,
            content=payload.question,
        )
        self.db.add(user_msg)
        await self.db.flush()

        rag_out = await self.rag_service.answer_question(
            question=payload.question,
            knowledge_bases=kbs,
            history=history,
            top_k=payload.top_k,
            metadata_filters=payload.metadata_filters,
        )

        assistant_msg = ChatMessage(
            organization_id=self.organization_id,
            session_id=session.id,
            user_id=user.id,
            role=MessageRole.ASSISTANT,
            content=rag_out.answer,
            model_used=rag_out.model_used,
            provider_used=rag_out.provider_used,
            prompt_tokens=rag_out.prompt_tokens,
            completion_tokens=rag_out.completion_tokens,
            confidence_score=rag_out.confidence_score,
            suggested_followups=rag_out.suggested_followups,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        citation_responses = await self._persist_citations(assistant_msg.id, rag_out.citations)
        await self._record_chat_usage(
            user_id=user.id,
            provider=rag_out.provider_used,
            model=rag_out.model_used,
            total_tokens=rag_out.prompt_tokens + rag_out.completion_tokens,
        )
        await self.db.commit()

        return ChatAnswerResponse(
            message_id=assistant_msg.id,
            answer=rag_out.answer,
            citations=citation_responses,
            confidence_score=rag_out.confidence_score,
            insufficient_context=rag_out.insufficient_context,
            suggested_followups=rag_out.suggested_followups,
            model_used=rag_out.model_used,
            provider_used=rag_out.provider_used,
        )

    async def stream_ask(
        self,
        *,
        session_id: uuid.UUID,
        user: User,
        role: OrganizationRole,
        question: str,
    ) -> AsyncIterator[str]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        await self.billing.assert_can_run_chat(self.organization_id)
        session = await self.get_session(session_id, user)
        kb_ids = [uuid.UUID(k) for k in session.knowledge_base_ids]
        kbs = await self.kb_service.validate_requested_kbs(kb_ids, user=user, role=role)
        history_rows = await self.message_repo.list_session_messages(session.id)
        history = [{"role": m.role.value, "content": m.content} for m in history_rows]

        user_msg = ChatMessage(
            organization_id=self.organization_id,
            session_id=session.id,
            user_id=user.id,
            role=MessageRole.USER,
            content=question,
        )
        self.db.add(user_msg)
        await self.db.commit()

        token_stream, used_chunks, confidence, insufficient, primary_kb = (
            await self.rag_service.stream_question(
                question=question,
                knowledge_bases=kbs,
                history=history,
            )
        )

        llm_provider = primary_kb.llm_provider
        llm_model = primary_kb.llm_model
        session_uuid = session.id
        user_uuid = user.id
        org_uuid = self.organization_id
        bind = self.db.get_bind()
        await self.db.close()

        post_session_factory = async_sessionmaker(
            bind=bind, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

        async def _event_stream() -> AsyncIterator[str]:
            collected: list[str] = []
            async for token in token_stream:
                collected.append(token)
                yield f"event: token\ndata: {json.dumps({'delta': token})}\n\n"

            full_answer = "".join(collected).strip()
            followups = RAGService.suggest_followups(question, used_chunks)

            async with post_session_factory() as post_db:
                post_chat = ChatService(post_db, org_uuid)
                assistant_msg = ChatMessage(
                    organization_id=org_uuid,
                    session_id=session_uuid,
                    user_id=user_uuid,
                    role=MessageRole.ASSISTANT,
                    content=full_answer,
                    model_used=llm_model,
                    provider_used=llm_provider,
                    confidence_score=confidence,
                    suggested_followups=followups,
                )
                post_db.add(assistant_msg)
                await post_db.flush()

                citation_responses = await post_chat._persist_citations(assistant_msg.id, used_chunks)
                await post_chat._record_chat_usage(
                    user_id=user_uuid,
                    provider=llm_provider,
                    model=llm_model,
                    total_tokens=max(1, len(full_answer.split()) + len(question.split())),
                )
                await post_db.commit()

            done_payload = {
                "message_id": str(assistant_msg.id),
                "citations": [c.model_dump(mode="json") for c in citation_responses],
                "confidence_score": confidence,
                "insufficient_context": insufficient,
                "suggested_followups": followups,
            }
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

        return _event_stream()

    async def regenerate_last(
        self, *, session_id: uuid.UUID, user: User, role: OrganizationRole
    ) -> ChatAnswerResponse:
        messages = await self.list_messages(session_id, user)
        last_user = next((m for m in reversed(messages) if m.role == MessageRole.USER), None)
        if not last_user:
            raise NotFoundError("No user prompt found in this session to regenerate")
        return await self.ask(
            session_id=session_id,
            user=user,
            role=role,
            payload=ChatAskRequest(question=last_user.content),
        )

    async def submit_feedback(
        self, *, message_id: uuid.UUID, user: User, payload: FeedbackCreateRequest
    ) -> Feedback:
        msg = (
            await self.db.execute(
                select(ChatMessage).where(
                    ChatMessage.id == message_id,
                    ChatMessage.organization_id == self.organization_id,
                )
            )
        ).scalar_one_or_none()
        if not msg:
            raise NotFoundError("Chat message not found")
        fb = Feedback(
            organization_id=self.organization_id,
            message_id=msg.id,
            user_id=user.id,
            rating=payload.rating,
            comment=payload.comment,
        )
        self.db.add(fb)
        await self.db.commit()
        await self.db.refresh(fb)
        return fb

    async def export_markdown(self, session_id: uuid.UUID, user: User) -> str:
        session = await self.get_session(session_id, user)
        messages = await self.message_repo.list_session_messages(session.id)
        lines = [f"# {session.title}\n"]
        for m in messages:
            role_label = "User" if m.role == MessageRole.USER else "KnowledgeForge AI"
            lines.append(f"## {role_label}\n\n{m.content}\n")
            if m.citations:
                lines.append("### Citations\n")
                for c in m.citations:
                    page_txt = f" (p.{c.page_number})" if c.page_number else ""
                    lines.append(f"- **{c.document_name}{page_txt}** (score {c.relevance_score:.2f})")
                lines.append("")
        return "\n".join(lines)

    async def _persist_citations(
        self, message_id: uuid.UUID, chunks: list[RetrievedChunk]
    ) -> list[CitationResponse]:
        responses: list[CitationResponse] = []
        for chunk in chunks:
            excerpt = chunk.content[:320].strip()
            citation = MessageCitation(
                organization_id=self.organization_id,
                message_id=message_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                document_name=chunk.document_name,
                page_number=chunk.page_number,
                source_url=chunk.source_url,
                excerpt=excerpt,
                relevance_score=chunk.relevance_score,
            )
            self.db.add(citation)
            responses.append(
                CitationResponse(
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    chunk_id=chunk.chunk_id,
                    page_number=chunk.page_number,
                    source_url=chunk.source_url,
                    excerpt=excerpt,
                    relevance_score=chunk.relevance_score,
                )
            )
        return responses

    async def _record_chat_usage(
        self, *, user_id: uuid.UUID, provider: str, model: str, total_tokens: int
    ) -> None:
        await self.billing.record_usage(
            organization_id=self.organization_id,
            user_id=user_id,
            metric_type="ai_request",
            quantity=1,
            provider=provider,
            model=model,
        )
        if total_tokens > 0:
            est_cost = round((total_tokens / 1000.0) * 0.002, 6)
            await self.billing.record_usage(
                organization_id=self.organization_id,
                user_id=user_id,
                metric_type="tokens",
                quantity=total_tokens,
                provider=provider,
                model=model,
                estimated_cost_usd=est_cost,
            )
