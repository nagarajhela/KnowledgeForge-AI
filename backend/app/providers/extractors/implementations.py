import csv
import io
import ipaddress
import json
import socket
from urllib.parse import urljoin, urlparse

import chardet
import httpx
from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from openpyxl import load_workbook
from pypdf import PdfReader

from app.core.exceptions import AppError
from app.providers.extractors.base import DocumentExtractor, ExtractedDocument, ExtractedPage

MAX_URL_REDIRECTS = 3
MAX_URL_DOWNLOAD_BYTES = 10 * 1024 * 1024


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        detected = chardet.detect(data)
        encoding = detected.get("encoding") or "latin-1"
        return data.decode(encoding, errors="replace")


class PDFExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        reader = PdfReader(io.BytesIO(data))
        pages: list[ExtractedPage] = []
        for idx, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(ExtractedPage(text=text, page_number=idx))
        return ExtractedDocument(pages=pages, page_count=len(reader.pages), title=filename)


class DocxExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        doc = DocxDocument(io.BytesIO(data))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        text = "\n".join(paragraphs)
        return ExtractedDocument(
            pages=[ExtractedPage(text=text, page_number=1)],
            page_count=1,
            title=filename,
        )


class TextExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        text = _decode_text(data).strip()
        return ExtractedDocument(
            pages=[ExtractedPage(text=text, page_number=1)] if text else [],
            page_count=1 if text else 0,
            title=filename,
        )


class CSVExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        text = _decode_text(data)
        reader = csv.reader(io.StringIO(text))
        rows = [", ".join(cell.strip() for cell in row) for row in reader if any(row)]
        content = "\n".join(rows)
        return ExtractedDocument(
            pages=[ExtractedPage(text=content, page_number=1)] if content else [],
            page_count=1,
            title=filename,
        )


class HTMLExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        html = _decode_text(data)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "nav", "footer"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else filename
        text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        return ExtractedDocument(
            pages=[ExtractedPage(text=text, page_number=1, section_title=title)] if text else [],
            page_count=1,
            title=title,
        )


class JSONExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        parsed = json.loads(_decode_text(data))
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        return ExtractedDocument(
            pages=[ExtractedPage(text=formatted, page_number=1)],
            page_count=1,
            title=filename,
        )


class XLSXExtractor(DocumentExtractor):
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        pages: list[ExtractedPage] = []
        for idx, sheet in enumerate(wb.worksheets, start=1):
            lines: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if vals:
                    lines.append(" | ".join(vals))
            if lines:
                pages.append(
                    ExtractedPage(
                        text="\n".join(lines),
                        page_number=idx,
                        section_title=sheet.title,
                    )
                )
        return ExtractedDocument(pages=pages, page_count=len(wb.worksheets), title=filename)


def assert_safe_public_url(url: str) -> None:
    """SSRF guard rejecting non-HTTP(S) schemes and private/loopback/link-local IP targets."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppError("Invalid URL scheme; only http/https are supported")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise AppError(f"Could not resolve hostname: {parsed.hostname}") from exc
    for info in infos:
        ip_str = info[4][0]
        ip_obj = ipaddress.ip_address(ip_str)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
        ):
            raise AppError("Target URL resolves to a restricted internal network address")


async def fetch_and_extract_url(url: str) -> ExtractedDocument:
    current_url = url
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        resp: httpx.Response | None = None
        for _ in range(MAX_URL_REDIRECTS + 1):
            assert_safe_public_url(current_url)
            resp = await client.get(
                current_url,
                headers={"User-Agent": "KnowledgeForgeAI-Crawler/1.0"},
            )
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise AppError("Redirect response missing Location header")
                current_url = urljoin(current_url, location)
                continue
            break
        else:
            raise AppError("Too many redirects while fetching target URL")

        assert resp is not None
        resp.raise_for_status()
        if len(resp.content) > MAX_URL_DOWNLOAD_BYTES:
            raise AppError("Fetched URL content exceeds maximum allowed 10 MB limit")
        content_type = resp.headers.get("content-type", "text/html").lower()
        if "json" in content_type:
            return JSONExtractor().extract(resp.content, filename=current_url)
        if "plain" in content_type or "markdown" in content_type:
            return TextExtractor().extract(resp.content, filename=current_url)
        return HTMLExtractor().extract(resp.content, filename=current_url)


def get_extractor(filename: str, mime_type: str) -> DocumentExtractor:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf" or mime_type == "application/pdf":
        return PDFExtractor()
    if ext == "docx" or "wordprocessingml" in mime_type:
        return DocxExtractor()
    if ext in {"txt", "md", "markdown"} or mime_type in {"text/plain", "text/markdown"}:
        return TextExtractor()
    if ext == "csv" or mime_type == "text/csv":
        return CSVExtractor()
    if ext in {"html", "htm"} or mime_type == "text/html":
        return HTMLExtractor()
    if ext == "json" or mime_type == "application/json":
        return JSONExtractor()
    if ext == "xlsx" or "spreadsheetml" in mime_type:
        return XLSXExtractor()
    raise AppError(f"Unsupported document type: {filename} ({mime_type})")
