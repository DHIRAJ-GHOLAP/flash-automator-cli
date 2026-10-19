"""Unit tests for PDF export, rendering, and file signature validation."""
from pathlib import Path
import pytest

from app.pdf_export import (
    PDFValidationError,
    build_printable_html_document,
    render_html_to_pdf,
    validate_pdf_data,
)
from app.report_parser import ReportParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_report_html() -> str:
    path = FIXTURES_DIR / "sample_report.html"
    return path.read_text(encoding="utf-8")


def test_validate_pdf_data_empty():
    is_valid, reason, _ = validate_pdf_data(b"")
    assert is_valid is False
    assert "empty" in reason.lower()


def test_validate_pdf_data_too_small():
    is_valid, reason, _ = validate_pdf_data(b"%PDF-1.4\nsome text")
    assert is_valid is False
    assert "too small" in reason.lower()


def test_validate_pdf_data_fake_html_renamed_to_pdf():
    fake_content = b"<html><body><h1>Login Page</h1></body></html>" + b"A" * 2000
    is_valid, reason, _ = validate_pdf_data(fake_content)
    assert is_valid is False
    assert "Missing PDF magic header" in reason


def test_build_printable_html_document():
    snippet = "<div id='receipt'><h2>Bank Account Wise Balance Statement</h2></div>"
    doc = build_printable_html_document(snippet)
    assert "<!DOCTYPE html>" in doc
    assert "@page" in doc
    assert "size: A4 landscape;" in doc
    assert snippet in doc


def test_render_html_to_pdf_real_sample(sample_report_html: str, tmp_path: Path):
    clean_html = ReportParser.extract_clean_printable_html(sample_report_html)
    out_file = tmp_path / "BankStatement_10-10-2026.pdf"

    generated_path = render_html_to_pdf(clean_html, out_file)
    assert generated_path.exists()
    assert generated_path == out_file

    pdf_bytes = generated_path.read_bytes()
    is_valid, reason, page_count = validate_pdf_data(pdf_bytes)
    assert is_valid is True
    assert page_count <= 4
    assert len(pdf_bytes) > 20000  # Multi-page rendered statement is large
