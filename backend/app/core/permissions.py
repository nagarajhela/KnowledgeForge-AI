from enum import StrEnum

from app.models.enums import OrganizationRole


class Permission(StrEnum):
    # Organization & Members
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    ORG_TRANSFER = "org:transfer"
    MEMBER_MANAGE = "member:manage"
    TEAM_MANAGE = "team:manage"
    AUDIT_READ = "audit:read"

    # Knowledge Bases & Documents
    KB_READ = "kb:read"
    KB_WRITE = "kb:write"
    KB_DELETE = "kb:delete"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_DELETE = "document:delete"

    # Chat & RAG
    CHAT_ASK = "chat:ask"

    # Analytics & API Keys
    ANALYTICS_READ = "analytics:read"
    API_KEY_MANAGE = "api_key:manage"

    # Billing
    BILLING_READ = "billing:read"
    BILLING_MANAGE = "billing:manage"


ROLE_PERMISSIONS: dict[OrganizationRole, set[Permission]] = {
    OrganizationRole.OWNER: set(Permission),
    OrganizationRole.ADMIN: {
        Permission.ORG_READ,
        Permission.ORG_UPDATE,
        Permission.MEMBER_MANAGE,
        Permission.TEAM_MANAGE,
        Permission.AUDIT_READ,
        Permission.KB_READ,
        Permission.KB_WRITE,
        Permission.KB_DELETE,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_DELETE,
        Permission.CHAT_ASK,
        Permission.ANALYTICS_READ,
        Permission.API_KEY_MANAGE,
        Permission.BILLING_READ,
    },
    OrganizationRole.EDITOR: {
        Permission.ORG_READ,
        Permission.KB_READ,
        Permission.KB_WRITE,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_DELETE,
        Permission.CHAT_ASK,
    },
    OrganizationRole.VIEWER: {
        Permission.ORG_READ,
        Permission.KB_READ,
        Permission.CHAT_ASK,
    },
    OrganizationRole.BILLING_MANAGER: {
        Permission.ORG_READ,
        Permission.BILLING_READ,
        Permission.BILLING_MANAGE,
    },
}


def has_permission(role: OrganizationRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
