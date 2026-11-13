from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ExternalResourceItem:
    external_id: str
    title: str
    mime_type: str
    content: bytes
    source_url: str | None = None


class ExternalConnector(ABC):
    """
    Replaceable connector interface for syncing external SaaS knowledge sources
    (Google Drive, Notion, Confluence, Slack, SharePoint).
    """

    provider_name: str

    @abstractmethod
    async def list_items(self, credentials: dict) -> list[ExternalResourceItem]:
        """Fetch updated documents from the external workspace."""


class StubExternalConnector(ExternalConnector):
    """Local scaffold implementation; swap with real OAuth API client per connector."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def list_items(self, credentials: dict) -> list[ExternalResourceItem]:
        return [
            ExternalResourceItem(
                external_id=f"{self.provider_name}-sample-1",
                title=f"{self.provider_name.title()} Synced Policy.md",
                mime_type="text/markdown",
                content=(
                    f"# {self.provider_name.title()} Knowledge Export\n\n"
                    "Configured via ExternalConnector adapter interface."
                ).encode("utf-8"),
                source_url=f"https://{self.provider_name}.example.com/docs/sample-1",
            )
        ]


CONNECTOR_REGISTRY: dict[str, ExternalConnector] = {
    name: StubExternalConnector(name)
    for name in ("google_drive", "notion", "confluence", "slack", "sharepoint")
}
