import asyncio

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.providers.storage.base import StorageProvider


class S3StorageProvider(StorageProvider):
    """S3-compatible storage adapter supporting MinIO locally and AWS S3 in production."""

    def __init__(self) -> None:
        self.bucket = settings.S3_BUCKET_NAME
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4"),
        )
        public_endpoint = settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL
        self._public_client = boto3.client(
            "s3",
            endpoint_url=public_endpoint,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4"),
        )

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        def _put() -> None:
            self._ensure_bucket()
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)
        return key

    async def download_bytes(self, key: str) -> bytes:
        def _get() -> bytes:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
            return bytes(resp["Body"].read())

        return await asyncio.to_thread(_get)

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        def _sign() -> str:
            return str(
                self._public_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
            )

        return await asyncio.to_thread(_sign)
