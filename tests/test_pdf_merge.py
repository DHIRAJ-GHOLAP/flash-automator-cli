"""Unit tests for PDF merging with blank separator page insertion."""
import datetime
from pathlib import Path
import pypdf
import pytest

from app.pdf_merge import (
    extract_date_from_filename,
    get_sorted_statement_pdfs,
    merge_statement_pdfs,
)


def _create_dummy_pdf(path: Path, num_pages: int = 1, text: str = "Test") -> Path:
    """Helper to create a small valid PDF with specified page count."""
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=595.0, height=842.0)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_extract_date_from_filename():
    d1 = extract_date_from_filename("BankStatement_01-07-2023.pdf")
    assert d1 == datetime.date(2023, 7, 1)

    d2 = extract_date_from_filename("BankStatement_31-10-2026.pdf")
    assert d2 == datetime.date(2026, 10, 31)

    assert extract_date_from_filename("Merged_BankStatements.pdf") is None
    assert extract_date_from_filename("random_file.pdf") is None


def test_get_sorted_statement_pdfs(tmp_path: Path):
    # Create out-of-order files
    _create_dummy_pdf(tmp_path / "BankStatement_15-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "BankStatement_02-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "Merged_BankStatements.pdf")  # Should be ignored

    sorted_files = get_sorted_statement_pdfs(tmp_path)
    assert len(sorted_files) == 3
    names = [f.name for f in sorted_files]
    assert names == [
        "BankStatement_01-07-2023.pdf",
        "BankStatement_02-07-2023.pdf",
        "BankStatement_15-07-2023.pdf",
    ]


def test_merge_statement_pdfs_with_blank_page(tmp_path: Path):
    # PDF 1: 3 pages
    # PDF 2: 2 pages
    p1 = _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf", num_pages=3)
    p2 = _create_dummy_pdf(tmp_path / "BankStatement_02-07-2023.pdf", num_pages=2)
    out_file = tmp_path / "Merged.pdf"

    merged_path, doc_count, total_pages = merge_statement_pdfs(
        pdf_paths=[p1, p2],
        output_path=out_file,
        insert_blank_page=True,
    )

    assert merged_path.exists()
    assert doc_count == 2
    # 3 (from p1) + 1 (blank separator) + 2 (from p2) = 6 total pages
    assert total_pages == 6

    # Verify via PdfReader
    reader = pypdf.PdfReader(str(merged_path))
    assert len(reader.pages) == 6


def test_merge_statement_pdfs_without_blank_page(tmp_path: Path):
    p1 = _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf", num_pages=3)
    p2 = _create_dummy_pdf(tmp_path / "BankStatement_02-07-2023.pdf", num_pages=2)
    out_file = tmp_path / "Merged_NoBlank.pdf"

    merged_path, doc_count, total_pages = merge_statement_pdfs(
        pdf_paths=[p1, p2],
        output_path=out_file,
        insert_blank_page=False,
    )

    assert merged_path.exists()
    assert doc_count == 2
    # 3 + 2 = 5 total pages
    assert total_pages == 5


def test_merge_statement_pdfs_empty_list():
    with pytest.raises(ValueError, match="No PDF files provided"):
        merge_statement_pdfs([], "/tmp/dummy.pdf")


from app.pdf_merge import (
    generate_final_cashbook,
    get_cashbook_ordered_pdfs,
    parse_period_string,
)


def test_parse_period_string():
    assert parse_period_string("07/2023") == (7, 2023)
    assert parse_period_string("7/2023") == (7, 2023)
    assert parse_period_string("07-2023") == (7, 2023)
    assert parse_period_string("2023-07") == (7, 2023)
    assert parse_period_string("July 2023") == (7, 2023)
    assert parse_period_string("july/2023") == (7, 2023)
    assert parse_period_string("OCTOBER 2026") == (10, 2026)

    with pytest.raises(ValueError, match="Unrecognized"):
        parse_period_string("invalid_period")


def test_get_cashbook_ordered_pdfs(tmp_path: Path):
    # Create files for Day 1 and Day 2 intentionally out of order
    _create_dummy_pdf(tmp_path / "PaymentSlip_01-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "BankStatement_02-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "DepositSlip_01-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "PaymentSlip_02-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "DepositSlip_02-07-2023.pdf")

    # Excluded files
    _create_dummy_pdf(tmp_path / "Merged_DepositSlips.pdf")
    _create_dummy_pdf(tmp_path / "Final_Cashbook_July_2023.pdf")

    ordered, month, year = get_cashbook_ordered_pdfs(tmp_path, month=7, year=2023)
    assert month == 7
    assert year == 2023
    assert len(ordered) == 6

    names = [f.name for f in ordered]
    assert names == [
        "BankStatement_01-07-2023.pdf",
        "DepositSlip_01-07-2023.pdf",
        "PaymentSlip_01-07-2023.pdf",
        "BankStatement_02-07-2023.pdf",
        "DepositSlip_02-07-2023.pdf",
        "PaymentSlip_02-07-2023.pdf",
    ]


def test_generate_final_cashbook(tmp_path: Path):
    # 2 dates, each with Bank, Deposit, and Payment (6 docs total, 1 page each)
    _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf", num_pages=1)
    _create_dummy_pdf(tmp_path / "DepositSlip_01-07-2023.pdf", num_pages=1)
    _create_dummy_pdf(tmp_path / "PaymentSlip_01-07-2023.pdf", num_pages=1)
    _create_dummy_pdf(tmp_path / "BankStatement_02-07-2023.pdf", num_pages=1)
    _create_dummy_pdf(tmp_path / "DepositSlip_02-07-2023.pdf", num_pages=1)
    _create_dummy_pdf(tmp_path / "PaymentSlip_02-07-2023.pdf", num_pages=1)

    out_file, doc_count, total_pages = generate_final_cashbook(
        input_dir=tmp_path,
        month=7,
        year=2023,
        insert_blank_page=True,
    )

    assert out_file.name == "Final_Cashbook_July_2023.pdf"
    assert doc_count == 6
    # 6 documents + 5 blank separator pages = 11 total pages
    assert total_pages == 11

    reader = pypdf.PdfReader(str(out_file))
    assert len(reader.pages) == 11


def test_generate_final_cashbook_extracts_last_page_for_multi_page_slips(tmp_path: Path):
    # Bank statement: 3 pages
    # Deposit slip: 4 pages (must be trimmed to last page only)
    # Payment slip: 5 pages (must be trimmed to last page only)
    _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf", num_pages=3)
    _create_dummy_pdf(tmp_path / "DepositSlip_01-07-2023.pdf", num_pages=4)
    _create_dummy_pdf(tmp_path / "PaymentSlip_01-07-2023.pdf", num_pages=5)

    out_file, doc_count, total_pages = generate_final_cashbook(
        input_dir=tmp_path,
        month=7,
        year=2023,
        insert_blank_page=True,
    )

    assert doc_count == 3
    # 3 (bank) + 1 (blank) + 1 (deposit last page) + 1 (blank) + 1 (payment last page) = 7 pages
    assert total_pages == 7

    reader = pypdf.PdfReader(str(out_file))
    assert len(reader.pages) == 7


