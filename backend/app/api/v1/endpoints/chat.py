import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.chat import (
    ChatAnswerResponse,
    ChatAskRequest,
    ChatMessageResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
    CitationResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["RAG Chat"])


@router.get(
    "/sessions",
    response_model=PaginatedResponse[ChatSessionResponse],
    summary="List chat sessions for the current user in the active organization",
)
async def list_sessions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ChatSessionResponse]:
    items, total = await ChatService(db, tenant.organization_id).list_sessions(
        tenant.user, offset=offset, limit=limit
    )
    return PaginatedResponse(
        items=[ChatSessionResponse.model_validate(s) for s in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new RAG chat session",
)
async def create_session(
    payload: ChatSessionCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    session = await ChatService(db, tenant.organization_id).create_session(
        tenant.user, tenant.role, payload
    )
    return ChatSessionResponse.model_validate(session)


@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionResponse,
    summary="Rename a chat session",
)
async def rename_session(
    session_id: uuid.UUID,
    payload: ChatSessionUpdateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    session = await ChatService(db, tenant.organization_id).rename_session(
        session_id, tenant.user, payload
    )
    return ChatSessionResponse.model_validate(session)


@router.delete(
    "/sessions/{session_id}",
    response_model=MessageResponse,
    summary="Delete a chat session",
)
async def delete_session(
    session_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await ChatService(db, tenant.organization_id).delete_session(session_id, tenant.user)
    return MessageResponse(message="Chat session deleted")


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessageResponse],
    summary="Get chat history with citations",
)
async def list_messages(
    session_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageResponse]:
    messages = await ChatService(db, tenant.organization_id).list_messages(session_id, tenant.user)
    return [
        ChatMessageResponse(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            model_used=m.model_used,
            provider_used=m.provider_used,
            prompt_tokens=m.prompt_tokens,
            completion_tokens=m.completion_tokens,
            confidence_score=m.confidence_score,
            suggested_followups=m.suggested_followups,
            citations=[
                CitationResponse(
                    document_id=c.document_id,
                    document_name=c.document_name,
                    chunk_id=c.chunk_id,
                    page_number=c.page_number,
                    source_url=c.source_url,
                    excerpt=c.excerpt,
                    relevance_score=c.relevance_score,
                )
                for c in m.citations
            ],
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatAnswerResponse,
    summary="Ask a question and receive grounded answer with citations",
)
async def ask_question(
    session_id: uuid.UUID,
    payload: ChatAskRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> ChatAnswerResponse:
    return await ChatService(db, tenant.organization_id).ask(
        session_id=session_id,
        user=tenant.user,
        role=tenant.role,
        payload=payload,
    )


@router.get(
    "/sessions/{session_id}/stream",
    summary="Stream grounded RAG answer tokens via Server-Sent Events (SSE)",
)
async def stream_question(
    session_id: uuid.UUID,
    question: str = Query(..., min_length=1, max_length=8000),
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    generator = await ChatService(db, tenant.organization_id).stream_ask(
        session_id=session_id,
        user=tenant.user,
        role=tenant.role,
        question=question,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/sessions/{session_id}/regenerate",
    response_model=ChatAnswerResponse,
    summary="Regenerate the last assistant answer in a session",
)
async def regenerate_answer(
    session_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> ChatAnswerResponse:
    return await ChatService(db, tenant.organization_id).regenerate_last(
        session_id=session_id,
        user=tenant.user,
        role=tenant.role,
    )


@router.post(
    "/messages/{message_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit thumbs up/down feedback on an assistant message",
)
async def submit_feedback(
    message_id: uuid.UUID,
    payload: FeedbackCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    fb = await ChatService(db, tenant.organization_id).submit_feedback(
        message_id=message_id, user=tenant.user, payload=payload
    )
    return FeedbackResponse.model_validate(fb)


@router.get(
    "/sessions/{session_id}/export",
    response_class=PlainTextResponse,
    summary="Export chat conversation and citations to Markdown",
)
async def export_chat_markdown(
    session_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.CHAT_ASK)),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    md = await ChatService(db, tenant.organization_id).export_markdown(session_id, tenant.user)
    return PlainTextResponse(content=md, media_type="text/markdown")
