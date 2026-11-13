import hashlib
import json
import os
import re
import socket
import uuid
from abc import ABC, abstractmethod

from app.core.config import settings
from app.core.exceptions import AppError
from app.providers.storage import get_storage_provider

ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/plain"},
    "markdown": {"text/markdown", "text/plain"},
    "csv": {"text/csv", "application/csv", "text/plain"},
    "html": {"text/html"},
    "htm": {"text/html"},
    "json": {"application/json", "text/plain"},
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    },
}

_BINARY_EXECUTABLE_PREFIXES = (
    b"\x7fELF",  # Linux ELF
    b"MZ",  # Windows PE/EXE/DLL
    b"\xfe\xed\xfa\xce",  # Mach-O 32
    b"\xfe\xed\xfa\xcf",  # Mach-O 64
    b"\xca\xfe\xba\xbe",  # Universal Mach-O / Java class
)


class VirusScannerInterface(ABC):
    @abstractmethod
    async def scan_bytes(self, data: bytes, filename: str) -> None:
        """Raise AppError if malware is detected."""


class NoOpVirusScanner(VirusScannerInterface):
    async def scan_bytes(self, data: bytes, filename: str) -> None:
        return None


class ClamAVVirusScanner(VirusScannerInterface):
    """Streams payload via INSTREAM protocol to clamd TCP socket."""

    async def scan_bytes(self, data: bytes, filename: str) -> None:
        import asyncio

        def _scan() -> str:
            with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=15) as sock:
                sock.sendall(b"zINSTREAM\0")
                chunk_size = 8192
                for i in range(0, len(data), chunk_size):
                    chunk = data[i : i + chunk_size]
                    sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
                sock.sendall((0).to_bytes(4, "big"))
                return sock.recv(4096).decode("utf-8", errors="replace")

        result = await asyncio.to_thread(_scan)
        if "FOUND" in result:
            raise AppError(f"Malware detected in uploaded file '{filename}'", error_code="malware_detected")


def get_virus_scanner() -> VirusScannerInterface:
    if settings.VIRUS_SCANNER_BACKEND == "clamav":
        return ClamAVVirusScanner()
    return NoOpVirusScanner()


class StorageService:
    """Handles secure upload validation, virus scanning, checksums, and S3/MinIO persistence."""

    def __init__(self) -> None:
        self.provider = get_storage_provider()
        self.scanner = get_virus_scanner()

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        base = os.path.basename(filename).strip()
        cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
        return cleaned[:240] or "document"

    @staticmethod
    def validate_upload(filename: str, content_type: str, size_bytes: int) -> str:
        if size_bytes <= 0:
            raise AppError("Uploaded file cannot be empty", error_code="empty_file")
        if size_bytes > settings.max_upload_bytes:
            raise AppError(
                f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB} MB",
                error_code="file_too_large",
            )
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise AppError(
                f"Unsupported file extension '.{ext}'",
                error_code="unsupported_file_type",
            )
        normalized_mime = content_type.split(";")[0].strip().lower()
        allowed_mimes = ALLOWED_EXTENSIONS[ext]
        if normalized_mime and normalized_mime not in allowed_mimes and normalized_mime != "application/octet-stream":
            raise AppError(
                f"MIME type '{normalized_mime}' does not match extension '.{ext}'",
                error_code="mime_mismatch",
            )
        return normalized_mime or next(iter(allowed_mimes))

    @staticmethod
    def validate_magic_bytes(filename: str, data: bytes) -> None:
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        head = data[:16]
        if any(head.startswith(sig) for sig in _BINARY_EXECUTABLE_PREFIXES):
            raise AppError(
                "Executable binary payloads are not permitted",
                error_code="invalid_file_signature",
            )
        if ext == "pdf":
            if b"%PDF-" not in data[:16]:
                raise AppError(
                    "Uploaded .pdf file failed PDF magic-byte verification",
                    error_code="invalid_file_signature",
                )
        elif ext in {"docx", "xlsx"}:
            if not (head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06")):
                raise AppError(
                    f"Uploaded .{ext} file failed Office OpenXML ZIP signature verification",
                    error_code="invalid_file_signature",
                )
        elif ext == "json":
            try:
                json.loads(data.decode("utf-8"))
            except Exception as exc:
                raise AppError(
                    "Uploaded .json file does not contain valid UTF-8 JSON",
                    error_code="invalid_file_signature",
                ) from exc
        elif ext in {"txt", "md", "markdown", "csv", "html", "htm"}:
            if b"\x00" in data[:4096]:
                raise AppError(
                    f"Uploaded .{ext} text file contains unexpected binary null bytes",
                    error_code="invalid_file_signature",
                )

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def store_document_bytes(
        self,
        *,
        organization_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
        document_id: uuid.UUID,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> tuple[str, str, str]:
        safe_name = self.sanitize_filename(filename)
        validated_mime = self.validate_upload(safe_name, content_type, len(data))
        self.validate_magic_bytes(safe_name, data)
        await self.scanner.scan_bytes(data, safe_name)
        checksum = self.compute_sha256(data)
        key = f"organizations/{organization_id}/knowledge_bases/{knowledge_base_id}/{document_id}/{safe_name}"
        await self.provider.upload_bytes(key, data, validated_mime)
        return key, checksum, validated_mime

    async def load_document_bytes(self, storage_path: str) -> bytes:
        return await self.provider.download_bytes(storage_path)

    async def get_signed_download_url(self, storage_path: str, expires_in: int = 900) -> str:
        return await self.provider.generate_presigned_download_url(storage_path, expires_in=expires_in)

    async def delete_document_object(self, storage_path: str) -> None:
        await self.provider.delete_object(storage_path)
