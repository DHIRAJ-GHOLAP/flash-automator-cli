"""Unit tests for response validation and HTML report parsing."""
from pathlib import Path
import pytest
from bs4 import BeautifulSoup

from app.report_parser import ReportParser, ReportValidationResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_report_html() -> str:
    path = FIXTURES_DIR / "sample_report.html"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def sample_no_records_html() -> str:
    path = FIXTURES_DIR / "sample_no_records.html"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def sample_login_html() -> str:
    path = FIXTURES_DIR / "sample_login.html"
    return path.read_text(encoding="utf-8")


def test_validate_response_real_report(sample_report_html: str):
    res = ReportParser.validate_response(sample_report_html)
    assert res.is_valid is True
    assert res.is_empty is False
    assert res.record_count > 100  # The real statement has 178 records
    assert res.from_date == "10/10/2026"
    assert res.to_date == "10/10/2026"
    assert res.title == "Bank Account Wise Balance Statement"
    assert res.error_message is None


def test_validate_response_no_records(sample_no_records_html: str):
    res = ReportParser.validate_response(sample_no_records_html)
    assert res.is_valid is True
    assert res.is_empty is True
    assert res.record_count == 0
    assert "account.no.record" in res.error_message


def test_validate_response_login_page(sample_login_html: str):
    res = ReportParser.validate_response(sample_login_html)
    assert res.is_valid is False
    assert "login" in res.error_message.lower()


def test_validate_response_empty_string():
    res = ReportParser.validate_response("")
    assert res.is_valid is False
    assert "Empty response" in res.error_message


def test_validate_response_missing_receipt_container():
    html = "<html><body><h1>Welcome</h1><p>Some random page</p></body></html>"
    res = ReportParser.validate_response(html)
    assert res.is_valid is False
    assert "Missing expected report container" in res.error_message


def test_validate_response_missing_title_keyword():
    html = "<div id='receipt'><table><tr><td>Data without title</td></tr></table></div>"
    res = ReportParser.validate_response(html)
    assert res.is_valid is False
    assert "missing expected title keyword" in res.error_message.lower()


def test_extract_clean_printable_html(sample_report_html: str):
    clean_html = ReportParser.extract_clean_printable_html(sample_report_html)
    soup = BeautifulSoup(clean_html, "html.parser")

    # Verify unwanted pagination elements are removed
    assert soup.find(class_="table-pagination") is None
    assert soup.find(class_="paging-nav") is None
    assert soup.find(class_="remove-btn") is None

    # Verify buttons removed
    assert len(soup.find_all("button")) == 0

    # Verify the table is preserved
    tables = soup.find_all("table")
    assert len(tables) == 1
    # Verify rows still present
    rows = tables[0].find_all("tr")
    assert len(rows) > 100
