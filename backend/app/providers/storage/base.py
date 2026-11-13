from abc import ABC, abstractmethod


class StorageProvider(ABC):
    """Abstract S3-compatible object storage interface."""

    @abstractmethod
    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        """Upload object bytes and return storage path/key."""

    @abstractmethod
    async def download_bytes(self, key: str) -> bytes:
        """Download object bytes by key."""

    @abstractmethod
    async def delete_object(self, key: str) -> None:
        """Delete object by key."""

    @abstractmethod
    async def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        """Generate temporary signed URL for secure download."""
