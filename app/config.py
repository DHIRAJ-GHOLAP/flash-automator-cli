"""Configuration module for KDMC MyNet HTTP Report Automation.

Loads settings from environment variables and .env files with safe defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False


DEFAULT_BASE_URL = "https://kdmc.gov.in/MainetService"
DEFAULT_REPORT_TYPE = "BAS"
DEFAULT_FIELD_ID = 4  # HO Main Branch
DEFAULT_ACCOUNT_HEAD_ID = 0  # All Accounts
DEFAULT_BIRT_OUTPUT_URL = "https://kdmc.gov.in/birtPA/output"
DEFAULT_ULB_NAME = 1  # Kalyan Dombivli Municipal Corporation
DEFAULT_WARD = 4  # HO Main Branch (Ward 4)
DEFAULT_BANK = 0  # ALL
DEFAULT_MODE = "X"  # ALL (Deposit Slip)
DEFAULT_PAYMENT_MODE = "0"  # ALL (Payment Slip)
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_REQUEST_DELAY = 1.5
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 1.5
DEFAULT_OUTPUT_DIR = "./output"
DEFAULT_DEBUG_DIR = "./debug"


@dataclass
class AppConfig:
    """Application configuration parameters."""
    base_url: str = DEFAULT_BASE_URL
    birt_output_url: str = DEFAULT_BIRT_OUTPUT_URL
    session_cookie: Optional[str] = None
    csrf_token: Optional[str] = None
    report_type_code: str = DEFAULT_REPORT_TYPE
    field_id: int = DEFAULT_FIELD_ID
    account_head_id: int = DEFAULT_ACCOUNT_HEAD_ID
    ulb_name: int = DEFAULT_ULB_NAME
    ward: int = DEFAULT_WARD
    bank: int = DEFAULT_BANK
    mode: str = DEFAULT_MODE
    payment_mode: str = DEFAULT_PAYMENT_MODE
    last_page_only: bool = True
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    request_delay: float = DEFAULT_REQUEST_DELAY
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    output_dir: Path = field(default_factory=lambda: Path(DEFAULT_OUTPUT_DIR))
    debug_dir: Path = field(default_factory=lambda: Path(DEFAULT_DEBUG_DIR))
    save_html: bool = False
    overwrite: bool = False

    @property
    def is_deposit_slip(self) -> bool:
        """True if the configured report type is Deposit Slip."""
        return self.report_type_code.upper() in (
            "DEPOSIT_SLIP",
            "DEPOSITSLIP",
            "DEPOSIT-SLIP",
            "DEPOSIT",
            "SLIP",
        )

    @property
    def is_payment_slip(self) -> bool:
        """True if the configured report type is Payment Slip."""
        return self.report_type_code.upper() in (
            "PAYMENT_SLIP",
            "PAYMENTSLIP",
            "PAYMENT-SLIP",
            "PAYMENT",
        )

    @property
    def is_birt_report(self) -> bool:
        """True if report is rendered by Eclipse BIRT engine."""
        return self.is_deposit_slip or self.is_payment_slip

    @property
    def filename_prefix(self) -> str:
        """Standard filename prefix for the active report type."""
        if self.is_deposit_slip:
            return "DepositSlip"
        elif self.is_payment_slip:
            return "PaymentSlip"
        return "BankStatement"

    @property
    def report_url(self) -> str:
        """URL for submitting report generation request."""
        return f"{self.base_url.rstrip('/')}/AccountFinancialReport.html?report"

    @property
    def on_report_type_url(self) -> str:
        """URL for triggering report type selection and receiving initial CSRF."""
        return f"{self.base_url.rstrip('/')}/AccountFinancialReport.html?onReportType"

    @property
    def daily_reports_url(self) -> str:
        """URL of the Daily Reports page (referer)."""
        return f"{self.base_url.rstrip('/')}/AccountDailyReports.html"

    @property
    def login_url(self) -> str:
        """URL of the login page."""
        return f"{self.base_url.rstrip('/')}/Login.html"


def load_config(env_path: Optional[Path | str] = None) -> AppConfig:
    """
    Load configuration from environment or specified .env file.
    Never raises on missing .env; falls back to environment variables and safe defaults.
    """
    if env_path is not None:
        load_dotenv(dotenv_path=Path(env_path), override=False)
    else:
        # Check standard locations
        for candidate in [Path(".env"), Path("../.env"), Path(__file__).resolve().parent.parent / ".env"]:
            if candidate.is_file():
                load_dotenv(dotenv_path=candidate, override=False)
                break

    session_cookie = (
        os.getenv("KDMC_SESSION_COOKIE")
        or os.getenv("JSESSIONID")
        or os.getenv("KDMC_JSESSIONID")
    )
    # Strip leading JSESSIONID= if present
    if session_cookie and session_cookie.startswith("JSESSIONID="):
        session_cookie = session_cookie.split("=", 1)[1]

    csrf_token = os.getenv("KDMC_CSRF_TOKEN") or os.getenv("CSRF_TOKEN")

    base_url = os.getenv("KDMC_BASE_URL", DEFAULT_BASE_URL).strip()
    report_type_code = os.getenv("KDMC_REPORT_TYPE", DEFAULT_REPORT_TYPE).strip()

    try:
        field_id = int(os.getenv("KDMC_FIELD_ID", str(DEFAULT_FIELD_ID)))
    except ValueError:
        field_id = DEFAULT_FIELD_ID

    try:
        account_head_id = int(os.getenv("KDMC_ACCOUNT_HEAD_ID", str(DEFAULT_ACCOUNT_HEAD_ID)))
    except ValueError:
        account_head_id = DEFAULT_ACCOUNT_HEAD_ID

    try:
        connect_timeout = float(os.getenv("KDMC_CONNECT_TIMEOUT", str(DEFAULT_CONNECT_TIMEOUT)))
    except ValueError:
        connect_timeout = DEFAULT_CONNECT_TIMEOUT

    try:
        read_timeout = float(os.getenv("KDMC_READ_TIMEOUT", str(DEFAULT_READ_TIMEOUT)))
    except ValueError:
        read_timeout = DEFAULT_READ_TIMEOUT

    try:
        request_delay = float(os.getenv("KDMC_REQUEST_DELAY", str(DEFAULT_REQUEST_DELAY)))
    except ValueError:
        request_delay = DEFAULT_REQUEST_DELAY

    try:
        max_retries = int(os.getenv("KDMC_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
    except ValueError:
        max_retries = DEFAULT_MAX_RETRIES

    birt_output_url = os.getenv("KDMC_BIRT_OUTPUT_URL", DEFAULT_BIRT_OUTPUT_URL).strip()
    try:
        ulb_name = int(os.getenv("KDMC_ULB_NAME", str(DEFAULT_ULB_NAME)))
    except ValueError:
        ulb_name = DEFAULT_ULB_NAME

    try:
        ward = int(os.getenv("KDMC_WARD", str(DEFAULT_WARD)))
    except ValueError:
        ward = DEFAULT_WARD

    try:
        bank = int(os.getenv("KDMC_BANK", str(DEFAULT_BANK)))
    except ValueError:
        bank = DEFAULT_BANK

    mode = os.getenv("KDMC_MODE", DEFAULT_MODE).strip()
    payment_mode = os.getenv("KDMC_PAYMENT_MODE", DEFAULT_PAYMENT_MODE).strip()
    last_page_only = os.getenv("KDMC_LAST_PAGE_ONLY", "true").lower() in ("true", "1", "yes")

    output_dir_str = os.getenv("KDMC_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    debug_dir_str = os.getenv("KDMC_DEBUG_DIR", DEFAULT_DEBUG_DIR)
    save_html_val = os.getenv("KDMC_SAVE_HTML", "false").lower() in ("true", "1", "yes")

    return AppConfig(
        base_url=base_url,
        birt_output_url=birt_output_url,
        session_cookie=session_cookie if session_cookie else None,
        csrf_token=csrf_token if csrf_token else None,
        report_type_code=report_type_code,
        field_id=field_id,
        account_head_id=account_head_id,
        ulb_name=ulb_name,
        ward=ward,
        bank=bank,
        mode=mode,
        payment_mode=payment_mode,
        last_page_only=last_page_only,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        request_delay=request_delay,
        max_retries=max_retries,
        output_dir=Path(output_dir_str),
        debug_dir=Path(debug_dir_str),
        save_html=save_html_val,
    )
