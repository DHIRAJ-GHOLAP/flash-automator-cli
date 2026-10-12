"""Report parsing and HTML response validation module.

Validates the presence of expected report containers, verifies report titles,
checks for error indicators, extracts printable HTML, and parses summary metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List
from bs4 import BeautifulSoup, Tag


@dataclass
class ReportValidationResult:
    """Result of validating a report HTTP response."""
    is_valid: bool
    record_count: int = 0
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    title: Optional[str] = None
    error_message: Optional[str] = None
    is_empty: bool = False


class ReportParser:
    """
    Parses and validates Bank Account Statement HTML responses from KDMC MyNet.
    """

    EXPECTED_TITLE_KEYWORD = "Bank Account Wise Balance Statement"

    @classmethod
    def validate_response(cls, html_content: str) -> ReportValidationResult:
        """
        Validate whether the returned HTML contains a valid Bank Account Statement.
        """
        if not html_content or not html_content.strip():
            return ReportValidationResult(
                is_valid=False,
                error_message="Empty response content received from server.",
            )

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Check for application error flags
        error_input = soup.find("input", id="errorId")
        if isinstance(error_input, Tag):
            val = error_input.get("value", "")
            if val == "Y":
                return ReportValidationResult(
                    is_valid=True,
                    is_empty=True,
                    error_message="No records found for the requested date (KDMC account.no.record).",
                )

        # 2. Check for receipt container
        receipt_div = soup.find(id="receipt")
        if not receipt_div:
            # Check if login or generic error page
            if "login" in html_content.lower() or "j_username" in html_content:
                return ReportValidationResult(
                    is_valid=False,
                    error_message="Response appears to be a login page, not a report.",
                )
            return ReportValidationResult(
                is_valid=False,
                error_message="Missing expected report container element (<div id='receipt'>).",
            )

        # 3. Check for expected title inside receipt
        text_content = receipt_div.get_text()
        if cls.EXPECTED_TITLE_KEYWORD.lower() not in text_content.lower():
            return ReportValidationResult(
                is_valid=False,
                error_message=f"Report container missing expected title keyword: '{cls.EXPECTED_TITLE_KEYWORD}'",
            )

        # 4. Check for table and row counts
        tables = receipt_div.find_all("table")
        if not tables:
            return ReportValidationResult(
                is_valid=False,
                error_message="No table element found inside report container.",
            )

        main_table = tables[0]
        # Count data rows in tbody or table (excluding header row and pagination rows)
        tbody = main_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else main_table.find_all("tr")

        # Filter out header and filter/pagination rows
        data_rows = []
        for r in rows:
            # Skip rows containing only th elements
            if r.find_all("th") and not r.find_all("td"):
                continue
            # Skip empty or pagination rows
            classes = r.get("class", [])
            if any(c in classes for c in ["tablesorter-filter-row", "tfoot", "table-pagination"]):
                continue
            data_rows.append(r)

        record_count = len(data_rows)

        # 5. Extract date metadata
        from_date = None
        to_date = None
        date_pattern = re.compile(
            r"From Date\s*:\s*(\d{2}/\d{2}/\d{4})\s+To Date\s*:\s*(\d{2}/\d{2}/\d{4})",
            re.IGNORECASE,
        )
        date_match = date_pattern.search(text_content)
        if date_match:
            from_date = date_match.group(1)
            to_date = date_match.group(2)

        return ReportValidationResult(
            is_valid=True,
            record_count=record_count,
            from_date=from_date,
            to_date=to_date,
            title=cls.EXPECTED_TITLE_KEYWORD,
            is_empty=(record_count == 0),
        )

    @classmethod
    def extract_clean_printable_html(cls, html_content: str) -> str:
        """
        Extract clean HTML from the receipt container, stripping client-side
        pagination controls, delete buttons, and scripts matching the frontend PrintDiv logic.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        receipt_div = soup.find(id="receipt")
        if not receipt_div:
            raise ValueError("Cannot extract printable HTML: <div id='receipt'> not found.")

        # Clone or modify the receipt div
        # Remove elements stripped by PrintDiv:
        # $(".table-pagination, .remove-btn, .paging-nav, .tfoot").remove();
        unwanted_classes = [
            "table-pagination",
            "remove-btn",
            "paging-nav",
            "ts-pager",
            "hidden-print",
            "tfoot",
        ]
        for unwanted in receipt_div.find_all(class_=unwanted_classes):
            unwanted.decompose()

        for btn in receipt_div.find_all(["button", "input"]):
            if btn.get("type") in ("button", "submit", "reset"):
                btn.decompose()

        # Clean table header sort classes
        for th in receipt_div.find_all("th"):
            th_classes = th.get("class", [])
            th["class"] = [
                c for c in th_classes
                if c not in ("tablesorter-headerDesc", "tablesorter-headerAsc", "tablesorter-header")
            ]

        # Strip inline styles on tr elements that may hide rows
        for tr in receipt_div.find_all("tr"):
            if "style" in tr.attrs:
                del tr.attrs["style"]

        return str(receipt_div)
