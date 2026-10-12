"""Unit tests for BatchRunner sequential processing and resilience."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from app.batch_runner import BatchRunner
from app.client import KDMCClient
from app.config import AppConfig
from app.date_engine import HTTPDateEngine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_report_html() -> str:
    path = FIXTURES_DIR / "sample_report.html"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def sample_no_records_html() -> str:
    path = FIXTURES_DIR / "sample_no_records.html"
    return path.read_text(encoding="utf-8")


def test_batch_runner_success_and_manifest(sample_report_html: str, tmp_path: Path):
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        output_dir=out_dir,
        request_delay=0.01,
        overwrite=False,
    )
    mock_client = MagicMock(spec=KDMCClient)
    mock_client.session_manager = MagicMock()
    mock_client.session_manager.csrf_token = "TEST_CSRF_TOKEN"

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.text = sample_report_html
    mock_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"
    mock_client.fetch_report.return_value = mock_resp

    engine = HTTPDateEngine(start_date="01/10/2026", end_date="02/10/2026")

    runner = BatchRunner(
        client=mock_client,
        config=config,
        date_engine=engine,
        resume=True,
    )

    results = runner.run()
    assert len(results) == 2
    assert results[0].status == "SUCCESS"
    assert results[1].status == "SUCCESS"
    assert mock_client.fetch_report.call_count == 2

    # Verify output PDF files generated
    pdf1 = out_dir / "BankStatement_01-10-2026.pdf"
    pdf2 = out_dir / "BankStatement_02-10-2026.pdf"
    assert pdf1.exists()
    assert pdf2.exists()

    # Verify manifest file
    manifest = out_dir / "execution_manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["total_processed"] == 2
    assert data["success_count"] == 2
    assert data["error_count"] == 0


def test_batch_runner_resumes_existing_files(sample_report_html: str, tmp_path: Path):
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        output_dir=out_dir,
        request_delay=0.01,
        overwrite=False,
    )
    mock_client = MagicMock(spec=KDMCClient)
    mock_client.session_manager = MagicMock()
    mock_client.session_manager.csrf_token = "TEST_CSRF_TOKEN"

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.text = sample_report_html
    mock_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"
    mock_client.fetch_report.return_value = mock_resp

    engine = HTTPDateEngine(start_date="01/10/2026", end_date="02/10/2026")

    # Run once to create files
    runner1 = BatchRunner(
        client=mock_client,
        config=config,
        date_engine=engine,
        resume=True,
    )
    runner1.run()
    assert mock_client.fetch_report.call_count == 2

    # Run again with resume=True: should skip both!
    mock_client.fetch_report.reset_mock()
    runner2 = BatchRunner(
        client=mock_client,
        config=config,
        date_engine=engine,
        resume=True,
    )
    results2 = runner2.run()
    assert len(results2) == 2
    assert results2[0].status == "SKIPPED"
    assert results2[1].status == "SKIPPED"
    # No HTTP calls made!
    assert mock_client.fetch_report.call_count == 0


def test_batch_runner_cancellation(sample_report_html: str, tmp_path: Path):
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        output_dir=out_dir,
        request_delay=0.01,
    )
    mock_client = MagicMock(spec=KDMCClient)
    mock_client.session_manager = MagicMock()
    mock_client.session_manager.csrf_token = "TEST_CSRF_TOKEN"

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.text = sample_report_html
    mock_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"
    mock_client.fetch_report.return_value = mock_resp

    engine = HTTPDateEngine(start_date="01/10/2026", end_date="05/10/2026")

    runner = BatchRunner(
        client=mock_client,
        config=config,
        date_engine=engine,
        resume=True,
    )

    # Cancel after first item
    def cancel_callback(idx, total, res):
        if idx == 1:
            runner.cancel()

    runner.progress_callback = cancel_callback
    results = runner.run()

    # Total 5 evaluated items: 1 processed (SUCCESS), 4 CANCELLED
    assert results[0].status == "SUCCESS"
    assert results[1].status == "CANCELLED"
    assert results[2].status == "CANCELLED"
    assert results[3].status == "CANCELLED"
    assert results[4].status == "CANCELLED"
    assert mock_client.fetch_report.call_count == 1
