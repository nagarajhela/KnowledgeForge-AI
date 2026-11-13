from pathlib import Path

from app.core.config import settings
from app.providers.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    """Filesystem storage fallback for unit tests and offline local development."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_path = Path(base_dir or settings.LOCAL_STORAGE_PATH).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_safe(self, key: str) -> Path:
        clean_key = key.lstrip("/")
        target = (self.base_path / clean_key).resolve()
        if not str(target).startswith(str(self.base_path)):
            raise ValueError("Invalid storage key path traversal attempt")
        return target

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        target = self._resolve_safe(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    async def download_bytes(self, key: str) -> bytes:
        target = self._resolve_safe(key)
        return target.read_bytes()

    async def delete_object(self, key: str) -> None:
        target = self._resolve_safe(key)
        if target.exists():
            target.unlink()

    async def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        return f"file://{self._resolve_safe(key)}?expires_in={expires_in}"
