from app.core.config import settings
from app.providers.storage.base import StorageProvider
from app.providers.storage.local import LocalStorageProvider
from app.providers.storage.s3 import S3StorageProvider


def get_storage_provider() -> StorageProvider:
    if settings.STORAGE_BACKEND == "local" or settings.APP_ENV == "test":
        return LocalStorageProvider()
    return S3StorageProvider()
