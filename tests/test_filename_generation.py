"""Unit tests for filename generation and duplicate protection."""
import datetime
from pathlib import Path
import pytest

from app.pdf_export import (
    format_date_for_filename,
    generate_filename,
    get_target_file_path,
)


def test_format_date_for_filename_from_string():
    assert format_date_for_filename("10/10/2026") == "10-10-2026"
    assert format_date_for_filename("01/05/2026") == "01-05-2026"
    assert format_date_for_filename("2026-10-10") == "10-10-2026"
    assert format_date_for_filename("15-08-2025") == "15-08-2025"


def test_format_date_for_filename_from_date_object():
    d = datetime.date(2026, 10, 10)
    assert format_date_for_filename(d) == "10-10-2026"


def test_format_date_for_filename_invalid():
    with pytest.raises(ValueError, match="Unrecognized date format"):
        format_date_for_filename("invalid-date")


def test_generate_filename_standard():
    assert generate_filename("10/10/2026") == "BankStatement_10-10-2026.pdf"
    assert generate_filename("01/01/2027") == "BankStatement_01-01-2027.pdf"
    assert generate_filename(datetime.date(2026, 10, 31)) == "BankStatement_31-10-2026.pdf"


def test_duplicate_protection_new_file(tmp_path: Path):
    target, already_exists = get_target_file_path(
        output_dir=tmp_path,
        date_input="10/10/2026",
        overwrite=False,
    )
    assert target.name == "BankStatement_10-10-2026.pdf"
    assert not already_exists


def test_duplicate_protection_existing_file_no_overwrite(tmp_path: Path):
    # Pre-create the file
    existing = tmp_path / "BankStatement_10-10-2026.pdf"
    existing.write_text("dummy")

    target, already_exists = get_target_file_path(
        output_dir=tmp_path,
        date_input="10/10/2026",
        overwrite=False,
    )
    assert target == existing
    assert already_exists is True


def test_duplicate_protection_existing_file_with_overwrite(tmp_path: Path):
    # Pre-create the file
    existing = tmp_path / "BankStatement_10-10-2026.pdf"
    existing.write_text("dummy")

    target, already_exists = get_target_file_path(
        output_dir=tmp_path,
        date_input="10/10/2026",
        overwrite=True,
    )
    assert target == existing
    assert already_exists is False
