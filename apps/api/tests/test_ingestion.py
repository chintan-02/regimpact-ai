from io import BytesIO
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from reportlab.pdfgen.canvas import Canvas

from regimpact.ingestion import (
    DevelopmentAllowScanner,
    DocumentValidationError,
    MalwareDetectedError,
    extract_document,
    validate_upload,
)
from regimpact.storage import LocalObjectStorage


class RejectScanner:
    def scan(self, content: bytes, filename: str) -> None:
        raise MalwareDetectedError("malware signature detected")


class DocumentValidationTests(TestCase):
    def test_rejects_extension_spoofing(self):
        with self.assertRaisesRegex(DocumentValidationError, "extension"):
            validate_upload(
                filename="directive.pdf",
                declared_media_type="application/pdf",
                content=b"<!doctype html><html><body>Not a PDF</body></html>",
                max_bytes=10_000,
                scanner=DevelopmentAllowScanner(),
            )

    def test_rejects_content_over_limit_before_parsing(self):
        with self.assertRaisesRegex(DocumentValidationError, "upload limit"):
            validate_upload(
                filename="directive.html",
                declared_media_type="text/html",
                content=b"<html>too large</html>",
                max_bytes=4,
                scanner=DevelopmentAllowScanner(),
            )

    def test_malware_scanner_can_fail_closed(self):
        with self.assertRaises(MalwareDetectedError):
            validate_upload(
                filename="directive.html",
                declared_media_type="text/html",
                content=b"<html><body>content</body></html>",
                max_bytes=10_000,
                scanner=RejectScanner(),
            )

    def test_html_extraction_removes_active_content_and_parses_sections(self):
        document = validate_upload(
            filename="directive.html",
            declared_media_type="text/html",
            content=b"""<!doctype html><html><body>
                <script>steal()</script>
                <h1>4.2 Incident notification</h1>
                <p>Report within 24 hours.</p>
                <h2>5 Records</h2><p>Retain records.</p>
            </body></html>""",
            max_bytes=10_000,
            scanner=DevelopmentAllowScanner(),
        )
        extracted = extract_document(document, max_pdf_pages=10)
        self.assertNotIn("steal", extracted.normalized_text)
        self.assertEqual([section.key for section in extracted.sections], ["4.2", "5"])
        self.assertEqual(extracted.sections[0].page, 1)

    def test_pdf_extraction_preserves_page_numbers(self):
        buffer = BytesIO()
        canvas = Canvas(buffer)
        canvas.drawString(72, 760, "1 Scope")
        canvas.drawString(72, 740, "This directive applies to operators.")
        canvas.showPage()
        canvas.drawString(72, 760, "2 Reporting")
        canvas.drawString(72, 740, "Report within 24 hours.")
        canvas.save()
        content = buffer.getvalue()
        document = validate_upload(
            filename="directive.pdf",
            declared_media_type="application/pdf",
            content=content,
            max_bytes=100_000,
            scanner=DevelopmentAllowScanner(),
        )
        extracted = extract_document(document, max_pdf_pages=10)
        self.assertEqual(len(extracted.pages), 2)
        self.assertEqual([section.page for section in extracted.sections], [1, 2])


class LocalObjectStorageTests(TestCase):
    def test_content_addressed_write_is_idempotent(self):
        with TemporaryDirectory() as directory:
            storage = LocalObjectStorage(directory)
            digest = "a" * 64
            organization_id = uuid4()
            uri_one = storage.put_document(
                organization_id=organization_id,
                object_key=digest,
                filename="directive.html",
                content=b"content",
            )
            uri_two = storage.put_document(
                organization_id=organization_id,
                object_key=digest,
                filename="directive.html",
                content=b"content",
            )
            self.assertEqual(uri_one, uri_two)
            self.assertEqual(storage.get_document(uri_one), b"content")

    def test_rejects_non_hash_object_key(self):
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "SHA-256"),
        ):
            LocalObjectStorage(directory).put_document(
                organization_id=uuid4(),
                object_key="../escape",
                filename="directive.pdf",
                content=b"content",
            )
