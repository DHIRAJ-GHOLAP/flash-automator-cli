"""Unit tests for Deposit Slip Report automation."""
import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.config import AppConfig
from app.client import KDMCClient
from app.batch_runner import BatchRunner
from app.date_engine import DateItem, HTTPDateEngine
from app.pdf_export import (
    extract_last_page_pdf,
    generate_filename,
    get_target_file_path,
    save_pdf_bytes,
    validate_pdf_data,
)
from app.pdf_merge import extract_date_from_filename, get_sorted_statement_pdfs


MOCK_PDF_BYTES = b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 842 595]/Parent 2 0 R>>endobj xref\n0 4\n0000000000 65535 f\n0000000015 00000 n\n0000000060 00000 n\n0000000111 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n" + b" " * 1000


def test_config_deposit_slip_properties():
    cfg_bas = AppConfig(report_type_code="BAS")
    assert not cfg_bas.is_deposit_slip
    assert cfg_bas.filename_prefix == "BankStatement"

    cfg_slip = AppConfig(report_type_code="deposit-slip")
    assert cfg_slip.is_deposit_slip
    assert cfg_slip.filename_prefix == "DepositSlip"

    cfg_slip2 = AppConfig(report_type_code="DEPOSIT_SLIP")
    assert cfg_slip2.is_deposit_slip
    assert cfg_slip2.filename_prefix == "DepositSlip"


def test_deposit_slip_filename_generation():
    fn = generate_filename("15/07/2023", prefix="DepositSlip")
    assert fn == "DepositSlip_15-07-2023.pdf"

    extracted = extract_date_from_filename(fn)
    assert extracted == datetime.date(2023, 7, 15)


def test_deposit_slip_target_file_path(tmp_path):
    target, exists = get_target_file_path(
        output_dir=tmp_path,
        date_input="15/07/2023",
        prefix="DepositSlip",
    )
    assert target.name == "DepositSlip_15-07-2023.pdf"
    assert not exists

    # Save mock file
    target.write_bytes(MOCK_PDF_BYTES)
    target2, exists2 = get_target_file_path(
        output_dir=tmp_path,
        date_input="15/07/2023",
        prefix="DepositSlip",
    )
    assert exists2


def test_save_pdf_bytes(tmp_path):
    out = tmp_path / "DepositSlip_01-07-2023.pdf"
    saved = save_pdf_bytes(MOCK_PDF_BYTES, out)
    assert saved.exists()
    assert saved.stat().st_size == len(MOCK_PDF_BYTES)

    is_valid, _, page_count = validate_pdf_data(saved.read_bytes())
    assert is_valid
    assert page_count >= 1


def test_fetch_deposit_slip_params():
    config = AppConfig(
        report_type_code="deposit-slip",
        birt_output_url="https://kdmc.gov.in/birtPA/output",
        ulb_name=1,
        ward=0,
        bank=0,
        mode="X",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = MOCK_PDF_BYTES
    mock_session.get.return_value = mock_resp

    client = KDMCClient(config=config, session=mock_session)
    resp = client.fetch_deposit_slip("05/07/2023")

    assert resp.status_code == 200
    mock_session.get.assert_called_once()
    called_args, called_kwargs = mock_session.get.call_args
    assert called_args[0] == "https://kdmc.gov.in/birtPA/output"
    params = called_kwargs["params"]
    assert params["__report"] == "DepositSlip_ReceiptDetailReport.rptdesign"
    assert params["__format"] == "pdf"
    assert params["ULBName"] == "1"
    assert params["Ward"] == "0"
    assert params["Bank"] == "0"
    assert params["Mode"] == "X"
    assert params["FromDate"] == "05/07/2023"
    assert params["ToDate"] == "05/07/2023"


def test_client_fetch_report_routing():
    config_slip = AppConfig(report_type_code="deposit-slip")
    client_slip = KDMCClient(config=config_slip)
    client_slip.fetch_deposit_slip = MagicMock()
    client_slip.fetch_bank_statement = MagicMock()

    client_slip.fetch_report("10/10/2026")
    client_slip.fetch_deposit_slip.assert_called_once_with("10/10/2026")
    client_slip.fetch_bank_statement.assert_not_called()

    config_bas = AppConfig(report_type_code="BAS")
    client_bas = KDMCClient(config=config_bas)
    client_bas.fetch_deposit_slip = MagicMock()
    client_bas.fetch_bank_statement = MagicMock()

    client_bas.fetch_report("10/10/2026")
    client_bas.fetch_bank_statement.assert_called_once_with("10/10/2026")
    client_bas.fetch_deposit_slip.assert_not_called()


def test_batch_runner_deposit_slip(tmp_path):
    config = AppConfig(
        report_type_code="deposit-slip",
        output_dir=tmp_path,
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = MOCK_PDF_BYTES
    mock_client.fetch_report.return_value = mock_resp

    engine = HTTPDateEngine("01/07/2023", "02/07/2023")
    runner = BatchRunner(config=config, client=mock_client, date_engine=engine)
    results = runner.run()

    assert len(results) == 2
    assert all(r.status == "SUCCESS" for r in results)
    assert (tmp_path / "DepositSlip_01-07-2023.pdf").exists()
    assert (tmp_path / "DepositSlip_02-07-2023.pdf").exists()


def test_get_sorted_statement_pdfs_with_prefix(tmp_path):
    (tmp_path / "BankStatement_01-07-2023.pdf").write_bytes(MOCK_PDF_BYTES)
    (tmp_path / "BankStatement_02-07-2023.pdf").write_bytes(MOCK_PDF_BYTES)
    (tmp_path / "DepositSlip_01-07-2023.pdf").write_bytes(MOCK_PDF_BYTES)
    (tmp_path / "DepositSlip_02-07-2023.pdf").write_bytes(MOCK_PDF_BYTES)

    slips = get_sorted_statement_pdfs(tmp_path, prefix="DepositSlip")
    assert len(slips) == 2
    assert all("DepositSlip" in p.name for p in slips)

    bas = get_sorted_statement_pdfs(tmp_path, prefix="BankStatement")
    assert len(bas) == 2
    assert all("BankStatement" in p.name for p in bas)


def create_multipage_pdf_bytes(num_pages: int = 3) -> bytes:
    """Helper to generate a multi-page PDF in memory."""
    import io
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Producer": "FlashAutomatorTest", "/Notes": "X" * 1500})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_config_payment_slip_properties():
    cfg = AppConfig(report_type_code="payment-slip")
    assert cfg.is_payment_slip
    assert cfg.is_birt_report
    assert not cfg.is_deposit_slip
    assert cfg.filename_prefix == "PaymentSlip"
    assert cfg.ward == 4  # HO Main Branch default
    assert cfg.field_id == 4  # HO Main Branch default
    assert cfg.payment_mode == "0"
    assert cfg.last_page_only is True


def test_extract_last_page_pdf():
    multi_page = create_multipage_pdf_bytes(4)
    is_valid, _, page_count = validate_pdf_data(multi_page)
    assert is_valid
    assert page_count == 4

    single_page = extract_last_page_pdf(multi_page)
    is_valid_single, _, single_count = validate_pdf_data(single_page)
    assert is_valid_single
    assert single_count == 1

    # Single-page input should return unchanged
    one_page = create_multipage_pdf_bytes(1)
    res_one = extract_last_page_pdf(one_page)
    _, _, count_one = validate_pdf_data(res_one)
    assert count_one == 1


def test_save_pdf_bytes_last_page_only(tmp_path):
    multi_page = create_multipage_pdf_bytes(3)
    out_last = tmp_path / "PaymentSlip_01-07-2023.pdf"
    save_pdf_bytes(multi_page, out_last, last_page_only=True)
    _, _, count_last = validate_pdf_data(out_last.read_bytes())
    assert count_last == 1

    out_all = tmp_path / "PaymentSlip_02-07-2023.pdf"
    save_pdf_bytes(multi_page, out_all, last_page_only=False)
    _, _, count_all = validate_pdf_data(out_all.read_bytes())
    assert count_all == 3


def test_fetch_payment_slip_params():
    config = AppConfig(
        report_type_code="payment-slip",
        birt_output_url="https://kdmc.gov.in/birtPA/output",
        ulb_name=1,
        ward=4,
        bank=0,
        payment_mode="0",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = MOCK_PDF_BYTES
    mock_session.get.return_value = mock_resp

    client = KDMCClient(config=config, session=mock_session)
    resp = client.fetch_payment_slip("03/07/2023")

    assert resp.status_code == 200
    mock_session.get.assert_called_once()
    called_args, called_kwargs = mock_session.get.call_args
    assert called_args[0] == "https://kdmc.gov.in/birtPA/output"
    params = called_kwargs["params"]
    assert params["__report"] == "DepositSlip_PaymentDetailReport.rptdesign"
    assert params["__format"] == "pdf"
    assert params["ULBName"] == "1"
    assert params["Ward"] == "4"
    assert params["Bank"] == "0"
    assert params["PaymentMode"] == "0"
    assert params["FromDate"] == "03/07/2023"
    assert params["ToDate"] == "03/07/2023"


def test_client_fetch_report_routing_payment_slip():
    config_pay = AppConfig(report_type_code="payment-slip")
    client_pay = KDMCClient(config=config_pay)
    client_pay.fetch_payment_slip = MagicMock()
    client_pay.fetch_deposit_slip = MagicMock()
    client_pay.fetch_bank_statement = MagicMock()

    client_pay.fetch_report("03/07/2023")
    client_pay.fetch_payment_slip.assert_called_once_with("03/07/2023")
    client_pay.fetch_deposit_slip.assert_not_called()
    client_pay.fetch_bank_statement.assert_not_called()


def test_batch_runner_payment_slip_last_page(tmp_path):
    config = AppConfig(
        report_type_code="payment-slip",
        output_dir=tmp_path,
        last_page_only=True,
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Server returns 5-page PDF
    mock_resp.content = create_multipage_pdf_bytes(5)
    mock_client.fetch_report.return_value = mock_resp

    engine = HTTPDateEngine("01/07/2023", "02/07/2023")
    runner = BatchRunner(config=config, client=mock_client, date_engine=engine)
    results = runner.run()

    assert len(results) == 2
    assert all(r.status == "SUCCESS" for r in results)
    f1 = tmp_path / "PaymentSlip_01-07-2023.pdf"
    f2 = tmp_path / "PaymentSlip_02-07-2023.pdf"
    assert f1.exists()
    assert f2.exists()
    # Ensure both files were reduced to 1 page
    _, _, c1 = validate_pdf_data(f1.read_bytes())
    _, _, c2 = validate_pdf_data(f2.read_bytes())
    assert c1 == 1
    assert c2 == 1

