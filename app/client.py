"""Authenticated HTTP client for KDMC MyNet portal.

Implements requests.Session management, Spring CSRF token synchronization,
parameter serialization, polite timeouts, and exponential backoff retries
for transient network errors without retrying authentication failures.
"""
from __future__ import annotations

import logging
import ssl
import time
from typing import Any, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.auth import SessionExpiredError, SessionManager
from app.config import AppConfig

logger = logging.getLogger("flash_automator.client")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class KDMCClientError(Exception):
    """Base exception for KDMC client errors."""
    pass


class KDMCNetworkError(KDMCClientError):
    """Raised when persistent network errors occur."""
    pass


from urllib3.util.ssl_ import create_urllib3_context


def build_legacy_compatible_ssl_context() -> ssl.SSLContext:
    """Create a context compatible with the portal's older TLS renegotiation behavior."""
    ctx = create_urllib3_context(ciphers="DEFAULT:@SECLEVEL=2")
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx


class KDMCSSLAdapter(HTTPAdapter):
    """
    SSL adapter that configures compatible cipher suites (DEFAULT:@SECLEVEL=2)
    to prevent TLS handshake resets from legacy government portal firewalls.
    """

    def init_poolmanager(self, *args, **kwargs):
        try:
            kwargs["ssl_context"] = build_legacy_compatible_ssl_context()
        except Exception:
            pass
        return super().init_poolmanager(*args, **kwargs)


class KDMCClient:
    """
    Client for interacting with the KDMC MyNet municipal portal.
    """

    def __init__(
        self,
        config: AppConfig,
        session_manager: Optional[SessionManager] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.session_manager = session_manager or SessionManager(
            session_cookie=config.session_cookie,
            csrf_token=config.csrf_token,
        )
        self.session = session or requests.Session()
        self.session.mount("https://", KDMCSSLAdapter())

        # Configure headers
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://kdmc.gov.in",
            "Referer": self.config.daily_reports_url,
            "X-Requested-With": "XMLHttpRequest",
        })

        # Apply cookies and existing tokens
        self.session_manager.apply_to_session(self.session)

    def refresh_csrf_token(self) -> Optional[str]:
        """
        Fetch the Daily Reports page or report type trigger to retrieve
        the latest valid CSRF token.
        """
        logger.debug("Requesting initial page to acquire/refresh CSRF token...")
        try:
            resp = self.session.get(
                self.config.daily_reports_url,
                timeout=(self.config.connect_timeout, self.config.read_timeout),
                allow_redirects=True,
            )
            # Check for session expiration on initial page
            is_expired, reason = self.session_manager.check_session_status(resp)
            if is_expired:
                raise SessionExpiredError(f"Session expired while fetching CSRF token: {reason}")

            token = self.session_manager.extract_csrf_from_html(resp.text)
            if token:
                logger.debug("Successfully extracted CSRF token from page metadata.")
                self.session.headers["X-CSRF-TOKEN"] = token
                return token

            # Fallback: trigger onReportType
            post_resp = self.session.post(
                self.config.on_report_type_url,
                data={"reportTypeCode": self.config.report_type_code},
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                timeout=(self.config.connect_timeout, self.config.read_timeout),
            )
            token = self.session_manager.extract_csrf_from_html(post_resp.text)
            if token:
                logger.debug("Successfully acquired CSRF token via onReportType.")
                self.session.headers["X-CSRF-TOKEN"] = token
                return token

        except requests.RequestException as e:
            logger.warning(f"Could not refresh CSRF token from server: {e}")

        return self.session_manager.csrf_token

    def build_report_payload(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """
        Construct exact URL-encoded parameter dictionary verified from HAR analysis.
        """
        return {
            "reportTypeCode": self.config.report_type_code,
            "transactionDate": "",
            "fromDate": from_date,
            "toDate": to_date,
            "accountHeadId": self.config.account_head_id,
            "financialId": "",
            "transactionTypeCode": "",
            "registerDepTypeId": "",
            "categoryId": "",
            "paymodeId": "",
            "vendorId": "",
            "fieldId": self.config.field_id,
        }

    def fetch_bank_statement(self, date_str: str) -> requests.Response:
        """
        Fetch Bank Account Statement for a single date (fromDate == toDate == date_str).
        Retries on transient network failures, but halts immediately on auth errors.
        """
        # Ensure CSRF token is present in header
        if self.session_manager.csrf_token:
            self.session.headers["X-CSRF-TOKEN"] = self.session_manager.csrf_token

        payload = self.build_report_payload(from_date=date_str, to_date=date_str)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        retries = 0
        backoff = self.config.retry_backoff

        while True:
            try:
                logger.debug(f"Submitting report request for date: {date_str} (attempt {retries + 1})")
                resp = self.session.post(
                    self.config.report_url,
                    data=payload,
                    headers=headers,
                    timeout=(self.config.connect_timeout, self.config.read_timeout),
                    allow_redirects=False,
                )

                # Check session expiration
                is_expired, reason = self.session_manager.check_session_status(resp)
                if is_expired:
                    logger.error(f"Authentication failure: {reason}")
                    raise SessionExpiredError(f"Session expired or invalid: {reason}")

                # Server errors: retryable
                if resp.status_code in (502, 503, 504):
                    if retries < self.config.max_retries:
                        retries += 1
                        logger.warning(
                            f"HTTP {resp.status_code} received. Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                        )
                        time.sleep(backoff)
                        backoff *= 1.5
                        continue
                    else:
                        resp.raise_for_status()

                if 200 <= resp.status_code < 300 and not (resp.text or "").strip():
                    if retries < self.config.max_retries:
                        retries += 1
                        logger.warning(
                            f"Empty HTTP {resp.status_code} response for {date_str}. "
                            f"Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                        )
                        time.sleep(backoff)
                        backoff *= 1.5
                        continue
                    raise KDMCNetworkError(
                        f"Persistent empty response requesting date {date_str} "
                        f"(HTTP {resp.status_code}) after {retries + 1} attempts."
                    )

                # Success or client response
                # Extract refreshed CSRF token if present
                self.session_manager.extract_csrf_from_html(resp.text)
                return resp

            except (requests.ConnectionError, requests.Timeout) as e:
                if retries < self.config.max_retries:
                    retries += 1
                    logger.warning(
                        f"Network error ({type(e).__name__}). Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                    )
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                else:
                    raise KDMCNetworkError(f"Persistent network failure requesting date {date_str}: {e}") from e

    def fetch_deposit_slip(self, date_str: str) -> requests.Response:
        """
        Fetch Deposit Slip Detail Receipt Report for a single date.
        Directly requests the BIRT output servlet and returns the server-generated PDF.
        """
        params = {
            "__report": "DepositSlip_ReceiptDetailReport.rptdesign",
            "__format": "pdf",
            "ULBName": str(self.config.ulb_name),
            "Ward": str(self.config.ward),
            "Bank": str(self.config.bank),
            "Mode": str(self.config.mode),
            "FromDate": date_str,
            "ToDate": date_str,
        }
        retries = 0
        backoff = self.config.retry_backoff

        while True:
            try:
                logger.debug(f"Requesting Deposit Slip PDF for date: {date_str} (attempt {retries + 1})")
                resp = self.session.get(
                    self.config.birt_output_url,
                    params=params,
                    timeout=(self.config.connect_timeout, self.config.read_timeout),
                    allow_redirects=True,
                )

                # Check session expiration
                is_expired, reason = self.session_manager.check_session_status(resp)
                if is_expired:
                    logger.error(f"Authentication failure: {reason}")
                    raise SessionExpiredError(f"Session expired or invalid: {reason}")

                if resp.status_code in (502, 503, 504):
                    if retries < self.config.max_retries:
                        retries += 1
                        logger.warning(
                            f"HTTP {resp.status_code} received. Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                        )
                        time.sleep(backoff)
                        backoff *= 1.5
                        continue
                    else:
                        resp.raise_for_status()

                return resp

            except (requests.ConnectionError, requests.Timeout) as e:
                if retries < self.config.max_retries:
                    retries += 1
                    logger.warning(
                        f"Network error ({type(e).__name__}). Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                    )
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                else:
                    raise KDMCNetworkError(f"Persistent network failure requesting date {date_str}: {e}") from e

    def fetch_payment_slip(self, date_str: str) -> requests.Response:
        """
        Fetch Deposit Slip Payment Detail Report for a single date.
        Directly requests the BIRT output servlet and returns the server-generated PDF.
        """
        params = {
            "__report": "DepositSlip_PaymentDetailReport.rptdesign",
            "__format": "pdf",
            "ULBName": str(self.config.ulb_name),
            "Ward": str(self.config.ward),
            "Bank": str(self.config.bank),
            "PaymentMode": str(self.config.payment_mode),
            "FromDate": date_str,
            "ToDate": date_str,
        }
        retries = 0
        backoff = self.config.retry_backoff

        while True:
            try:
                logger.debug(f"Requesting Payment Slip PDF for date: {date_str} (attempt {retries + 1})")
                resp = self.session.get(
                    self.config.birt_output_url,
                    params=params,
                    timeout=(self.config.connect_timeout, self.config.read_timeout),
                    allow_redirects=True,
                )

                # Check session expiration
                is_expired, reason = self.session_manager.check_session_status(resp)
                if is_expired:
                    logger.error(f"Authentication failure: {reason}")
                    raise SessionExpiredError(f"Session expired or invalid: {reason}")

                if resp.status_code in (502, 503, 504):
                    if retries < self.config.max_retries:
                        retries += 1
                        logger.warning(
                            f"HTTP {resp.status_code} received. Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                        )
                        time.sleep(backoff)
                        backoff *= 1.5
                        continue
                    else:
                        resp.raise_for_status()

                return resp

            except (requests.ConnectionError, requests.Timeout) as e:
                if retries < self.config.max_retries:
                    retries += 1
                    logger.warning(
                        f"Network error ({type(e).__name__}). Retrying in {backoff:.1f}s (attempt {retries}/{self.config.max_retries})..."
                    )
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                else:
                    raise KDMCNetworkError(f"Persistent network failure requesting date {date_str}: {e}") from e

    def fetch_monthly_income_expenditure(
        self,
        report_type: str,
        year: int,
        month: int,
    ) -> requests.Response:
        """Fetch the month-wise Income or Expenditure classification report."""
        params = {
            "__report": "MonthlyClassificationofReports.rptdesign",
            "__format": "pdf",
            "ULBName": str(self.config.ulb_name),
            "ReportType": report_type,
            "SubReportType": "WM",
            "Year": str(year),
            "Month": str(month),
        }
        retries = 0
        backoff = self.config.retry_backoff

        while True:
            try:
                logger.debug(
                    "Requesting monthly %s report for %02d/%d (attempt %d)",
                    report_type,
                    month,
                    year,
                    retries + 1,
                )
                resp = self.session.get(
                    self.config.birt_output_url,
                    params=params,
                    timeout=(self.config.connect_timeout, self.config.read_timeout),
                    allow_redirects=True,
                )

                is_expired, reason = self.session_manager.check_session_status(resp)
                if is_expired:
                    logger.error("Authentication failure: %s", reason)
                    raise SessionExpiredError(f"Session expired or invalid: {reason}")

                if resp.status_code in (502, 503, 504):
                    if retries < self.config.max_retries:
                        retries += 1
                        logger.warning(
                            "HTTP %s received. Retrying in %.1fs (attempt %s/%s)...",
                            resp.status_code,
                            backoff,
                            retries,
                            self.config.max_retries,
                        )
                        time.sleep(backoff)
                        backoff *= 1.5
                        continue
                    resp.raise_for_status()

                return resp

            except (requests.ConnectionError, requests.Timeout) as e:
                if retries < self.config.max_retries:
                    retries += 1
                    logger.warning(
                        "Network error (%s). Retrying in %.1fs (attempt %s/%s)...",
                        type(e).__name__,
                        backoff,
                        retries,
                        self.config.max_retries,
                    )
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                raise KDMCNetworkError(
                    f"Persistent network failure requesting monthly {report_type} report "
                    f"for {month:02d}/{year}: {e}"
                ) from e

    def fetch_report(self, date_str: str) -> requests.Response:
        """
        Fetch report for a single date, routing dynamically based on configured report type.
        """
        if self.config.is_deposit_slip:
            return self.fetch_deposit_slip(date_str)
        elif self.config.is_payment_slip:
            return self.fetch_payment_slip(date_str)
        return self.fetch_bank_statement(date_str)
