"""Secure document validation, extraction and section parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Protocol

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .domain import Section


class DocumentValidationError(ValueError):
    """Raised when uploaded bytes violate the ingestion contract."""


class MalwareDetectedError(DocumentValidationError):
    pass


class MalwareScannerUnavailableError(RuntimeError):
    pass


class MalwareScanner(Protocol):
    def scan(self, content: bytes, filename: str) -> None: ...


class DevelopmentAllowScanner:
    """Local-only scanner. Production configuration must fail closed without a real scanner."""

    def scan(self, content: bytes, filename: str) -> None:
        return None


class UnavailableScanner:
    def scan(self, content: bytes, filename: str) -> None:
        raise MalwareScannerUnavailableError("malware scanning service is unavailable")


@dataclass(frozen=True, slots=True)
class ValidatedDocument:
    filename: str
    media_type: str
    content: bytes
    content_hash: str


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    media_type: str
    pages: tuple[ExtractedPage, ...]
    sections: tuple[Section, ...]

    @property
    def normalized_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages).strip()


PDF_SIGNATURE = b"%PDF-"
HTML_PREFIXES = (b"<!doctype html", b"<html", b"<?xml")
SECTION_HEADING = re.compile(
    r"^(?P<key>(?:section\s+)?\d+(?:\.\d+)*[A-Za-z]?)\s*[-–—.:]?\s+(?P<title>\S.*)$",
    re.IGNORECASE,
)


def validate_upload(
    *,
    filename: str,
    declared_media_type: str | None,
    content: bytes,
    max_bytes: int,
    scanner: MalwareScanner,
) -> ValidatedDocument:
    if not filename or filename in {".", ".."}:
        raise DocumentValidationError("filename is required")
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if len(safe_name) > 240 or safe_name.startswith("."):
        raise DocumentValidationError("filename is not allowed")
    if not content:
        raise DocumentValidationError("document is empty")
    if len(content) > max_bytes:
        raise DocumentValidationError(f"document exceeds the {max_bytes}-byte upload limit")

    probe = content[:512].lstrip().lower()
    expected_extension: str | tuple[str, ...]
    if content.startswith(PDF_SIGNATURE):
        detected = "application/pdf"
        expected_extension = ".pdf"
    elif any(probe.startswith(prefix) for prefix in HTML_PREFIXES):
        detected = "text/html"
        expected_extension = (".html", ".htm")
    else:
        raise DocumentValidationError("only signature-verified PDF and HTML files are accepted")

    if not safe_name.lower().endswith(expected_extension):
        raise DocumentValidationError("file extension does not match detected content")
    if declared_media_type and declared_media_type.split(";", 1)[0].lower() not in {
        detected,
        "application/octet-stream",
    }:
        raise DocumentValidationError("declared media type does not match detected content")

    scanner.scan(content, safe_name)
    return ValidatedDocument(
        filename=safe_name,
        media_type=detected,
        content=content,
        content_hash=sha256(content).hexdigest(),
    )


def extract_document(document: ValidatedDocument, *, max_pdf_pages: int) -> ExtractedDocument:
    if document.media_type == "application/pdf":
        pages = _extract_pdf(document.content, max_pdf_pages=max_pdf_pages)
    elif document.media_type == "text/html":
        pages = _extract_html(document.content)
    else:
        raise DocumentValidationError("unsupported validated media type")

    sections = _parse_sections(pages)
    if not sections:
        raise DocumentValidationError("document contains no extractable text")
    return ExtractedDocument(media_type=document.media_type, pages=pages, sections=sections)


def _extract_pdf(content: bytes, *, max_pdf_pages: int) -> tuple[ExtractedPage, ...]:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
    except PdfReadError as exc:
        raise DocumentValidationError("PDF structure is invalid") from exc
    if reader.is_encrypted:
        raise DocumentValidationError("encrypted PDFs are not accepted")
    if len(reader.pages) > max_pdf_pages:
        raise DocumentValidationError(f"PDF exceeds the {max_pdf_pages}-page limit")
    pages = tuple(
        ExtractedPage(number=index, text=_normalize_text(page.extract_text() or ""))
        for index, page in enumerate(reader.pages, start=1)
    )
    if not any(page.text for page in pages):
        raise DocumentValidationError("PDF contains no extractable text; OCR is not yet enabled")
    return pages


def _extract_html(content: bytes) -> tuple[ExtractedPage, ...]:
    soup = BeautifulSoup(content, "html.parser")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    text = _normalize_text(soup.get_text("\n"))
    if not text:
        raise DocumentValidationError("HTML document contains no extractable text")
    return (ExtractedPage(number=1, text=text),)


def _parse_sections(pages: tuple[ExtractedPage, ...]) -> tuple[Section, ...]:
    sections: list[Section] = []
    current_key: str | None = None
    current_heading = "Document text"
    current_page: int | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        text = "\n".join(body).strip()
        if text:
            key = current_key or f"page-{current_page or 1}"
            sections.append(Section(key=key, heading=current_heading, text=text, page=current_page))
        body = []

    for page in pages:
        for line in page.text.splitlines():
            match = SECTION_HEADING.match(line.strip())
            if match:
                flush()
                current_key = match.group("key").lower().removeprefix("section ")
                current_heading = match.group("title").strip()
                current_page = page.number
            else:
                if current_page is None:
                    current_page = page.number
                body.append(line)
        if current_key is None:
            flush()
            current_page = None
    flush()

    if not sections:
        return ()
    seen: dict[str, int] = {}
    unique: list[Section] = []
    for section in sections:
        count = seen.get(section.key, 0) + 1
        seen[section.key] = count
        key = section.key if count == 1 else f"{section.key}-{count}"
        unique.append(
            Section(key=key, heading=section.heading, text=section.text, page=section.page)
        )
    return tuple(unique)


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()
