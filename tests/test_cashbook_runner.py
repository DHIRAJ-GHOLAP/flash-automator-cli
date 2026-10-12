"""Unit tests for CashbookRunner and cashbook CLI command."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pypdf
import pytest
import requests

from app.batch_runner import CashbookRunner
from app.cli import build_parser, cmd_cashbook, main
from app.config import AppConfig


def _create_dummy_pdf(path: Path, num_pages: int = 1) -> Path:
    """Helper to create a valid minimal PDF."""
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=595.0, height=842.0)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_cashbook_runner_with_existing_files(tmp_path: Path):
    """Test that CashbookRunner recognizes existing valid files and compiles the cashbook."""
    # Create files for Day 1 and Day 2 of July 2023
    for day in (1, 2):
        _create_dummy_pdf(tmp_path / f"BankStatement_{day:02d}-07-2023.pdf", num_pages=1)
        _create_dummy_pdf(tmp_path / f"DepositSlip_{day:02d}-07-2023.pdf", num_pages=1)
        _create_dummy_pdf(tmp_path / f"PaymentSlip_{day:02d}-07-2023.pdf", num_pages=1)

    mock_client = MagicMock()
    config = AppConfig(output_dir=tmp_path)

    # CashbookRunner for July 2023, skipping dates beyond Day 2 to keep test fast
    with patch("app.batch_runner.HTTPDateEngine") as MockDateEngine:
        import datetime
        mock_item1 = MagicMock(date_str="01/07/2023", date=datetime.date(2023, 7, 1), is_included=True, weekday_name="Saturday")
        mock_item2 = MagicMock(date_str="02/07/2023", date=datetime.date(2023, 7, 2), is_included=True, weekday_name="Sunday")

        engine_instance = MagicMock()
        engine_instance.get_all_items.return_value = [mock_item1, mock_item2]
        MockDateEngine.return_value = engine_instance

        runner = CashbookRunner(
            client=mock_client,
            config=config,
            month=7,
            year=2023,
            date_engine=engine_instance,
            resume=True,
        )

        out_path, reports_merged, total_pages = runner.run()

        assert out_path.exists()
        assert out_path.name == "Final_Cashbook_July_2023.pdf"
        assert reports_merged == 6
        assert total_pages == 11  # 6 docs + 5 blank separator pages

        # Because files were valid and resume=True, client should not have been called
        mock_client.fetch_bank_statement.assert_not_called()
        mock_client.fetch_deposit_slip.assert_not_called()
        mock_client.fetch_payment_slip.assert_not_called()


def test_cashbook_runner_downloads_missing_files(tmp_path: Path):
    """Test CashbookRunner downloads missing slips and bank statements when not present."""
    mock_client = MagicMock()

    fixtures_dir = Path(__file__).parent / "fixtures"
    sample_html = (fixtures_dir / "sample_report.html").read_text(encoding="utf-8")
    bas_response = MagicMock(spec=requests.Response)
    bas_response.text = sample_html
    mock_client.fetch_bank_statement.return_value = bas_response

    # Create dummy PDF bytes for slip responses (multi-page to test last-page extraction)
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    import io
    pdf_buf = io.BytesIO()
    writer.write(pdf_buf)
    dummy_pdf_bytes = pdf_buf.getvalue()

    slip_response = MagicMock(spec=requests.Response)
    slip_response.content = dummy_pdf_bytes
    mock_client.fetch_deposit_slip.return_value = slip_response
    mock_client.fetch_payment_slip.return_value = slip_response

    config = AppConfig(output_dir=tmp_path, request_delay=0.0)

    import datetime
    mock_item = MagicMock(date_str="01/07/2023", date=datetime.date(2023, 7, 1), is_included=True, weekday_name="Saturday")

    engine = MagicMock()
    engine.get_all_items.return_value = [mock_item]

    with patch("app.batch_runner.render_html_to_pdf") as mock_render:
        def fake_render(html, target):
            _create_dummy_pdf(target, num_pages=2)
            return target
        mock_render.side_effect = fake_render

        runner = CashbookRunner(
            client=mock_client,
            config=config,
            month=7,
            year=2023,
            date_engine=engine,
            resume=True,
        )

        out_path, reports_merged, total_pages = runner.run()

        mock_client.fetch_bank_statement.assert_called_once_with("01/07/2023")
        mock_client.fetch_deposit_slip.assert_called_once_with("01/07/2023")
        mock_client.fetch_payment_slip.assert_called_once_with("01/07/2023")

        assert out_path.exists()
        assert reports_merged == 3


def test_cli_cashbook_command(tmp_path: Path):
    """Test full CLI cashbook command parsing and execution."""
    # Pre-populate day 1 files
    _create_dummy_pdf(tmp_path / "BankStatement_01-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "DepositSlip_01-07-2023.pdf")
    _create_dummy_pdf(tmp_path / "PaymentSlip_01-07-2023.pdf")

    parser = build_parser()
    args = parser.parse_args(["cashbook", "--period", "07/2023", "--output-dir", str(tmp_path), "--skip-download"])
    config = AppConfig()

    exit_code = cmd_cashbook(args, config)
    assert exit_code == 0
    assert (tmp_path / "Final_Cashbook_July_2023.pdf").exists()
