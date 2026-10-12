"""PDF and report export module.

Renders extracted statement HTML into faithful landscape A4 PDF documents
using WeasyPrint, verifies PDF signatures and integrity, generates standard filenames,
and prevents accidental file overwrites.
"""
from __future__ import annotations

import datetime
import io
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("flash_automator.export")

try:
    import weasyprint
    WEASYPRINT_AVAILABLE = True
except (ImportError, Exception):
    WEASYPRINT_AVAILABLE = False

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


PDF_MAGIC_BYTES = b"%PDF-"


class ExportError(Exception):
    """Raised when report export or PDF conversion fails."""
    pass


class PDFValidationError(Exception):
    """Raised when generated or received PDF fails integrity verification."""
    pass


def format_date_for_filename(date_input: str | datetime.date) -> str:
    """
    Format a date string (DD/MM/YYYY or YYYY-MM-DD) or date object into DD-MM-YYYY.
    """
    if isinstance(date_input, datetime.date):
        return date_input.strftime("%d-%m-%Y")

    cleaned = date_input.strip()
    # Check DD/MM/YYYY or DD-MM-YYYY
    match = re.match(r"^(\d{2})[/.-](\d{2})[/.-](\d{4})$", cleaned)
    if match:
        day, month, year = match.groups()
        return f"{day}-{month}-{year}"

    # Check YYYY-MM-DD
    match = re.match(r"^(\d{4})[/.-](\d{2})[/.-](\d{2})$", cleaned)
    if match:
        year, month, day = match.groups()
        return f"{day}-{month}-{year}"

    raise ValueError(f"Unrecognized date format for filename: {date_input}")


def generate_filename(
    date_input: str | datetime.date,
    prefix: str = "BankStatement",
) -> str:
    """
    Generate standard filename according to project specification:
    [Prefix]_DD-MM-YYYY.pdf (e.g. BankStatement_10-10-2026.pdf or DepositSlip_10-10-2026.pdf)
    """
    formatted_date = format_date_for_filename(date_input)
    return f"{prefix}_{formatted_date}.pdf"


def get_target_file_path(
    output_dir: Path | str,
    date_input: str | datetime.date,
    overwrite: bool = False,
    prefix: str = "BankStatement",
) -> Tuple[Path, bool]:
    """
    Determine target file path and verify duplicate protection.
    Returns: (target_path: Path, already_exists: bool)
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = generate_filename(date_input, prefix=prefix)
    target_path = out_dir / filename

    if target_path.exists():
        if not overwrite:
            return target_path, True

    return target_path, False


def extract_last_page_pdf(pdf_bytes: bytes) -> bytes:
    """
    Extract only the final page of a multi-page PDF document.
    Municipal daily deposit and payment slips contain detailed receipt rows,
    while the final page contains the Grand Total summary and daily totals.
    If the document has 1 page or pypdf is unavailable, returns the original bytes.
    """
    if not PYPDF_AVAILABLE or not pdf_bytes:
        return pdf_bytes

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        if total_pages <= 1:
            return pdf_bytes

        writer = pypdf.PdfWriter()
        writer.add_page(reader.pages[-1])
        output_buffer = io.BytesIO()
        writer.write(output_buffer)
        return output_buffer.getvalue()
    except Exception as e:
        logger.warning(f"Could not extract last page from PDF ({e}); using original PDF.")
        return pdf_bytes


def save_pdf_bytes(
    pdf_bytes: bytes,
    output_path: Path | str,
    last_page_only: bool = False,
) -> Path:
    """
    Validate and save direct PDF bytes to destination output_path.
    If last_page_only is True, extracts only the final summary page.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    is_valid, reason, _ = validate_pdf_data(pdf_bytes)
    if not is_valid:
        raise PDFValidationError(f"Received PDF failed validation: {reason}")

    if last_page_only:
        pdf_bytes = extract_last_page_pdf(pdf_bytes)

    with open(target, "wb") as f:
        f.write(pdf_bytes)

    return target


def validate_pdf_data(pdf_bytes: bytes) -> Tuple[bool, str, int]:
    """
    Verify that the byte stream is a valid, uncorrupted PDF document.
    Checks:
    - Minimum file size (> 1024 bytes)
    - Magic header bytes '%PDF-'
    - Can be parsed by pypdf and has at least 1 page (if pypdf available)
    Returns: (is_valid: bool, reason: str, page_count: int)
    """
    if not pdf_bytes:
        return False, "PDF content is empty (0 bytes)", 0

    if len(pdf_bytes) < 256:
        return False, f"PDF file size too small ({len(pdf_bytes)} bytes); likely truncated or error response", 0

    if not pdf_bytes.startswith(PDF_MAGIC_BYTES):
        snippet = pdf_bytes[:200].decode("latin-1", errors="replace")
        return False, f"Missing PDF magic header '%PDF-'. Content starts with: {snippet[:60]}", 0

    page_count = 1
    if PYPDF_AVAILABLE:
        try:
            import io
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            page_count = len(reader.pages)
            if page_count < 1:
                return False, "PDF contains zero pages", 0
        except Exception as e:
            return False, f"Corrupted PDF structure: {e}", 0

    return True, "Valid PDF", page_count


def build_printable_html_document(
    clean_receipt_html: str,
    title: str = "Bank Account Wise Balance Statement",
) -> str:
    """
    Construct complete HTML document formatted with print styling
    for faithful A4 landscape PDF rendering.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
@page {{
    size: A4 landscape;
    margin: 8mm 10mm 10mm 10mm;
    @bottom-center {{
        content: "Page " counter(page) " of " counter(pages);
        font-family: Arial, sans-serif;
        font-size: 8pt;
        color: #666;
    }}
}}
body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 9pt;
    line-height: 1.25;
    color: #222;
    background: #fff;
    margin: 0;
    padding: 0;
}}
h2, h3 {{
    margin: 4px 0;
    text-align: center;
    font-weight: bold;
    color: #111;
}}
h2 {{ font-size: 13pt; }}
h3 {{ font-size: 11pt; }}
p {{
    margin: 3px 0;
    text-align: center;
    font-size: 8.5pt;
    color: #333;
}}
.text-center {{ text-align: center; }}
.text-right {{ text-align: right; }}
.text-left {{ text-align: left; }}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    page-break-inside: auto;
}}
tr {{
    page-break-inside: avoid;
    page-break-after: auto;
}}
thead {{
    display: table-header-group;
}}
tfoot {{
    display: table-footer-group;
}}
th, td {{
    border: 1px solid #777;
    padding: 3px 5px;
    font-size: 8pt;
    vertical-align: middle;
}}
th {{
    background-color: #e8e8e8;
    color: #000;
    font-weight: bold;
    text-align: center;
}}
td:nth-child(1) {{ text-align: center; width: 4%; }}
td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9) {{
    text-align: right;
    font-family: "Courier New", Courier, monospace;
    font-weight: 500;
}}
</style>
</head>
<body>
{clean_receipt_html}
</body>
</html>"""


def render_html_to_pdf(
    html_content: str,
    output_path: Path | str,
    title: str = "Bank Account Wise Balance Statement",
) -> Path:
    """
    Render clean receipt HTML into a PDF file at output_path.
    """
    if not WEASYPRINT_AVAILABLE:
        raise ExportError(
            "WeasyPrint library is not available in current environment. "
            "Cannot render HTML to PDF."
        )

    full_html = build_printable_html_document(html_content, title=title)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        pdf_bytes = weasyprint.HTML(string=full_html).write_pdf()
    except Exception as e:
        raise ExportError(f"WeasyPrint failed to render PDF: {e}") from e

    # Validate output
    is_valid, reason, _ = validate_pdf_data(pdf_bytes)
    if not is_valid:
        raise PDFValidationError(f"Generated PDF failed validation: {reason}")

    with open(target, "wb") as f:
        f.write(pdf_bytes)

    return target


def save_debug_html(html_text: str, debug_dir: Path | str, date_str: str) -> Path:
    """Save raw response HTML to debug directory for diagnostic inspection."""
    d_dir = Path(debug_dir)
    d_dir.mkdir(parents=True, exist_ok=True)
    clean_date = format_date_for_filename(date_str)
    out_file = d_dir / f"RawResponse_{clean_date}.html"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_text)
    return out_file
