from fastapi import APIRouter

from app.api.v1.endpoints import (
    analytics,
    api_keys,
    auth,
    billing,
    chat,
    documents,
    health,
    ingestion,
    invitations,
    knowledge_bases,
    members,
    organizations,
    providers,
    teams,
    users,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(organizations.router)
api_router.include_router(members.router)
api_router.include_router(invitations.router)
api_router.include_router(teams.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(documents.router)
api_router.include_router(ingestion.router)
api_router.include_router(chat.router)
api_router.include_router(analytics.router)
api_router.include_router(api_keys.router)
api_router.include_router(billing.router)
api_router.include_router(providers.router)
api_router.include_router(webhooks.router)
