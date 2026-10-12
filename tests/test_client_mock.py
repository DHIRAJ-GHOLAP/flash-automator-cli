"""Unit tests for KDMCClient with mocked HTTP interactions.

Ensures zero live HTTP requests to the municipal portal during automated testing.
"""
from unittest.mock import MagicMock, patch
import pytest
import requests

from app.auth import SessionExpiredError, SessionManager
from app.client import KDMCClient, KDMCNetworkError
from app.config import AppConfig


@pytest.fixture
def mock_config() -> AppConfig:
    return AppConfig(
        base_url="https://kdmc.gov.in/MainetService",
        session_cookie="TEST_SESSION_COOKIE_VALUE_12345",
        csrf_token="86d644c8-6121-4fe0-8da7-32c044d06823",
        field_id=4,
        account_head_id=0,
        max_retries=2,
        retry_backoff=0.01,  # Fast retries for testing
    )


def test_payload_construction(mock_config: AppConfig):
    client = KDMCClient(mock_config)
    payload = client.build_report_payload(from_date="10/10/2026", to_date="10/10/2026")

    assert payload["reportTypeCode"] == "BAS"
    assert payload["fromDate"] == "10/10/2026"
    assert payload["toDate"] == "10/10/2026"
    assert payload["accountHeadId"] == 0
    assert payload["fieldId"] == 4
    assert payload["transactionDate"] == ""
    assert payload["financialId"] == ""
    assert payload["transactionTypeCode"] == ""
    assert payload["registerDepTypeId"] == ""
    assert payload["categoryId"] == ""
    assert payload["paymodeId"] == ""
    assert payload["vendorId"] == ""


def test_session_cookie_and_csrf_headers(mock_config: AppConfig):
    client = KDMCClient(mock_config)
    assert client.session.cookies.get("JSESSIONID") == "TEST_SESSION_COOKIE_VALUE_12345"
    assert client.session.headers.get("X-CSRF-TOKEN") == "86d644c8-6121-4fe0-8da7-32c044d06823"
    assert client.session.headers.get("X-Requested-With") == "XMLHttpRequest"
    assert "kdmc.gov.in" in client.session.headers.get("Origin")


def test_fetch_report_success(mock_config: AppConfig):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.is_redirect = False
    mock_resp.text = "<div id='receipt'><h2>Bank Account Wise Balance Statement</h2></div>"
    mock_resp.headers = {}
    mock_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"

    client = KDMCClient(mock_config)
    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        resp = client.fetch_report("10/10/2026")
        assert resp == mock_resp
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["data"]["fromDate"] == "10/10/2026"
        assert kwargs["data"]["toDate"] == "10/10/2026"
        assert kwargs["data"]["reportTypeCode"] == "BAS"


def test_fetch_report_auth_failure_no_retries(mock_config: AppConfig):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 401
    mock_resp.is_redirect = False
    mock_resp.text = "Unauthorized"
    mock_resp.headers = {}
    mock_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"

    client = KDMCClient(mock_config)
    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(SessionExpiredError, match="HTTP 401 Unauthorized"):
            client.fetch_report("10/10/2026")
        # Must NOT retry on authentication failure
        assert mock_post.call_count == 1


def test_fetch_report_redirect_to_login_no_retries(mock_config: AppConfig):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 302
    mock_resp.is_redirect = True
    mock_resp.headers = {"Location": "https://kdmc.gov.in/MainetService/Login.html"}
    mock_resp.text = "Redirecting"
    mock_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"

    client = KDMCClient(mock_config)
    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(SessionExpiredError, match="Redirected to login endpoint"):
            client.fetch_report("10/10/2026")
        assert mock_post.call_count == 1


def test_fetch_report_retries_transient_server_error(mock_config: AppConfig):
    mock_error_resp = MagicMock(spec=requests.Response)
    mock_error_resp.status_code = 503
    mock_error_resp.is_redirect = False
    mock_error_resp.text = "Service Temporarily Unavailable"
    mock_error_resp.headers = {}
    mock_error_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"

    mock_ok_resp = MagicMock(spec=requests.Response)
    mock_ok_resp.status_code = 200
    mock_ok_resp.is_redirect = False
    mock_ok_resp.text = "<div id='receipt'><h2>Bank Account Wise Balance Statement</h2></div>"
    mock_ok_resp.headers = {}
    mock_ok_resp.url = "https://kdmc.gov.in/MainetService/AccountFinancialReport.html?report"

    client = KDMCClient(mock_config)
    # Fail once with 503, succeed on second attempt
    with patch.object(client.session, "post", side_effect=[mock_error_resp, mock_ok_resp]) as mock_post:
        resp = client.fetch_report("10/10/2026")
        assert resp == mock_ok_resp
        assert mock_post.call_count == 2


def test_fetch_report_connection_error_exhausts_retries(mock_config: AppConfig):
    client = KDMCClient(mock_config)
    with patch.object(client.session, "post", side_effect=requests.ConnectionError("Connection timed out")) as mock_post:
        with pytest.raises(KDMCNetworkError, match="Persistent network failure"):
            client.fetch_report("10/10/2026")
        # max_retries is 2, so initial try + 2 retries = 3 calls
        assert mock_post.call_count == 3
