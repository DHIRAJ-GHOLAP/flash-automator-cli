"""PDF merging module with blank separator page insertion.

Merges daily bank statement PDFs chronologically and inserts exactly one
blank/empty page between consecutive statements for clean duplex/physical filing separation.
"""
from __future__ import annotations

import datetime
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

logger = logging.getLogger("flash_automator.merge")

DATE_PATTERN = re.compile(
    r"(?:BankStatement|DepositSlip|PaymentSlip|\w+)[-_](\d{2})[-_](\d{2})[-_](\d{4})",
    re.IGNORECASE,
)

MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_period_string(period_str: str) -> Tuple[int, int]:
    """
    Parse period strings like '07/2023', 'July 2023', '2023-07', '07-2023' into (month: int, year: int).
    """
    clean = period_str.strip()
    # Numeric MM/YYYY or MM-YYYY
    m = re.match(r"^(\d{1,2})[/.-](\d{4})$", clean)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return month, year
    # Numeric YYYY/MM or YYYY-MM
    m = re.match(r"^(\d{4})[/.-](\d{1,2})$", clean)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return month, year
    # Name Month Year e.g. 'July 2023', 'July/2023'
    m = re.match(r"^([a-zA-Z]+)[/\s._-]+(\d{4})$", clean)
    if m:
        name, year = m.group(1).lower(), int(m.group(2))
        if name in MONTH_NAMES:
            return MONTH_NAMES[name], year
    raise ValueError(f"Unrecognized month/year period format: '{period_str}'. Expected 'MM/YYYY' or 'Month YYYY'.")


def extract_date_from_filename(filename: str) -> Optional[datetime.date]:
    """Extract datetime.date from a statement filename like BankStatement_10-07-2023.pdf, DepositSlip_10-07-2023.pdf, or PaymentSlip_10-07-2023.pdf."""
    match = DATE_PATTERN.search(filename)
    if match:
        day, month, year = match.groups()
        try:
            return datetime.date(int(year), int(month), int(day))
        except ValueError:
            return None
    return None


def get_month_output_dir(input_dir: Path | str, month: int, year: int) -> Path:
    """Return the output folder for a month, named like 'July_2023'."""
    month_name = datetime.date(year, month, 1).strftime("%B")
    return Path(input_dir) / f"{month_name}_{year}"


def organize_month_pdfs(input_dir: Path | str, month: int, year: int) -> Path:
    """Move matching root-level source and generated PDFs into their month folder."""
    root = Path(input_dir)
    root.mkdir(parents=True, exist_ok=True)
    month_dir = get_month_output_dir(root, month, year)
    month_dir.mkdir(parents=True, exist_ok=True)
    month_name = datetime.date(year, month, 1).strftime("%B")
    generated_suffix = f"_{month_name}_{year}.pdf".lower()

    for source in root.glob("*.pdf"):
        report_date = extract_date_from_filename(source.name)
        is_monthly_output = (
            source.name.startswith(("Merged_", "Final_Cashbook_"))
            and source.name.lower().endswith(generated_suffix)
        )
        belongs_to_month = (
            report_date is not None
            and report_date.month == month
            and report_date.year == year
        ) or is_monthly_output
        if not belongs_to_month:
            continue

        destination = month_dir / source.name
        if destination.exists():
            raise FileExistsError(
                f"Cannot organize {source}: destination already exists ({destination})"
            )
        shutil.move(str(source), str(destination))
        logger.info("Moved %s into %s", source.name, month_dir.name)

    return month_dir


def get_sorted_statement_pdfs(
    input_dir: Path | str,
    prefix: Optional[str] = None,
) -> List[Path]:
    """
    Scan input_dir for statement/slip PDFs and sort them chronologically by report date.
    Files that do not match the date pattern are sorted alphabetically at the end.
    Optionally filters by prefix (e.g. 'BankStatement' or 'DepositSlip').
    """
    directory = Path(input_dir)
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    pdf_files = list(directory.rglob("*.pdf"))
    # Exclude any previously generated merged PDFs or cashbooks
    pdf_files = [
        f for f in pdf_files
        if not f.name.startswith("Merged_")
        and "merged" not in f.name.lower()
        and "cashbook" not in f.name.lower()
    ]

    if prefix:
        clean_prefix = prefix.strip().lower()
        pdf_files = [f for f in pdf_files if f.name.lower().startswith(clean_prefix)]

    def sort_key(path: Path) -> Tuple[int, datetime.date, str]:
        extracted_date = extract_date_from_filename(path.name)
        if extracted_date is not None:
            return (0, extracted_date, path.name)
        return (1, datetime.date.max, path.name)

    return sorted(pdf_files, key=sort_key)


def generate_monthly_report_merges(
    input_dir: Path | str,
    month: int,
    year: int,
    insert_blank_page: bool = True,
) -> List[Tuple[Path, int, int]]:
    """Merge each report type for one month into its own period-specific PDF."""
    month_name = datetime.date(year, month, 1).strftime("%B")
    merged_outputs: List[Tuple[Path, int, int]] = []
    report_types = (
        ("BankStatement", "BankStatements"),
        ("DepositSlip", "DepositSlips"),
        ("PaymentSlip", "PaymentSlips"),
    )

    for prefix, output_label in report_types:
        monthly_files = [
            path
            for path in get_sorted_statement_pdfs(input_dir, prefix=prefix)
            if (report_date := extract_date_from_filename(path.name)) is not None
            and report_date.month == month
            and report_date.year == year
        ]
        if not monthly_files:
            logger.warning("No %s PDFs found for %s %s; skipping category merge.", prefix, month_name, year)
            continue

        output_path = Path(input_dir) / f"Merged_{output_label}_{month_name}_{year}.pdf"
        merged_outputs.append(
            merge_statement_pdfs(
                pdf_paths=monthly_files,
                output_path=output_path,
                insert_blank_page=insert_blank_page,
            )
        )

    return merged_outputs


def merge_statement_pdfs(
    pdf_paths: List[Path],
    output_path: Path | str,
    insert_blank_page: bool = True,
    only_last_page_for_slips: bool = False,
) -> Tuple[Path, int, int]:
    """
    Merge a list of PDF files into a single document.
    
    Args:
        pdf_paths: Ordered list of PDF file paths to merge.
        output_path: Destination path for the merged PDF.
        insert_blank_page: If True, inserts one blank page between consecutive PDFs.
                          (No blank page is added after the final PDF).
        only_last_page_for_slips: If True, only extracts the final summary page of
                                  deposit slip and payment slip PDFs.
                          
    Returns:
        Tuple of (output_path: Path, total_documents_merged: int, total_pages_in_output: int)
    """
    if not PYPDF_AVAILABLE:
        raise RuntimeError("pypdf is required to merge PDF files. Install it via 'pip install pypdf'.")

    if not pdf_paths:
        raise ValueError("No PDF files provided to merge.")

    writer = pypdf.PdfWriter()
    total_docs = len(pdf_paths)

    for i, path in enumerate(pdf_paths, start=1):
        logger.debug(f"Adding [{i}/{total_docs}]: {path.name}")
        try:
            reader = pypdf.PdfReader(str(path))
            doc_pages = len(reader.pages)
            if doc_pages == 0:
                logger.warning(f"Skipping empty PDF: {path.name}")
                continue

            # Check if this document is a deposit slip or payment slip
            # Updated code:
            is_deposit = "deposit" in path.name.lower()
            is_payment = "payment" in path.name.lower()

            # Determine whether this specific file should be reduced to 1 page
            should_trim_to_last_page = False
            if only_last_page_for_slips and doc_pages > 1:
                if is_deposit:
                    should_trim_to_last_page = True
                elif is_payment:
                    should_trim_to_last_page = only_last_page_for_payment

            if should_trim_to_last_page:
                logger.debug(f"Extracting only the last summary page for {path.name} ({doc_pages} pages -> 1 page)")
                writer.add_page(reader.pages[-1])
            else:
                for page in reader.pages:
                    writer.add_page(page)

            # Insert one blank page between documents (not after the last document)
            if insert_blank_page and i < total_docs:
                first_page = reader.pages[0]
                width = float(first_page.mediabox.width)
                height = float(first_page.mediabox.height)
                writer.add_blank_page(width=width, height=height)
                logger.debug(f"Inserted 1 blank separator page after {path.name}")

        except Exception as e:
            logger.error(f"Error reading {path.name}: {e}")
            raise RuntimeError(f"Failed to read and merge {path.name}: {e}") from e

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with open(out_file, "wb") as f:
        writer.write(f)

    total_pages = len(writer.pages)
    logger.info(
        f"Merged {total_docs} PDFs into {out_file.name} "
        f"({total_pages} total pages, blank_separator={insert_blank_page})"
    )
    return out_file, total_docs, total_pages


def get_cashbook_ordered_pdfs(
    input_dir: Path | str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Tuple[List[Path], int, int]:
    """
    Scan input_dir and assemble PDFs in the municipal Cashbook daily sequence:
    For each date chronologically:
      1. Bank Account Statement (BankStatement_DD-MM-YYYY.pdf)
      2. Deposit Slip (DepositSlip_DD-MM-YYYY.pdf)
      3. Payment Slip (PaymentSlip_DD-MM-YYYY.pdf)

    Returns:
      (ordered_pdf_paths: List[Path], selected_month: int, selected_year: int)
    """
    directory = Path(input_dir)
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    pdf_files = list(directory.rglob("*.pdf"))
    # Exclude any merged files or existing cashbooks
    pdf_files = [
        f for f in pdf_files
        if not f.name.startswith("Merged_")
        and "merged" not in f.name.lower()
        and "cashbook" not in f.name.lower()
    ]

    # Map files by date
    files_by_date: Dict[datetime.date, List[Path]] = {}
    for f in pdf_files:
        dt = extract_date_from_filename(f.name)
        if dt is not None:
            files_by_date.setdefault(dt, []).append(f)

    if not files_by_date:
        raise ValueError(f"No valid dated statement/slip PDFs found in directory: {directory}")

    # Auto-detect month/year if not provided
    if month is None or year is None:
        periods = {(d.year, d.month) for d in files_by_date.keys()}
        if len(periods) == 1:
            detected_year, detected_month = next(iter(periods))
            year = year or detected_year
            month = month or detected_month
        elif month is not None:
            matching_years = {d.year for d in files_by_date.keys() if d.month == month}
            if matching_years:
                year = max(matching_years)
            else:
                raise ValueError(f"No statement files found for month {month} in {directory}")
        elif year is not None:
            matching_months = {d.month for d in files_by_date.keys() if d.year == year}
            if len(matching_months) == 1:
                month = next(iter(matching_months))
            else:
                raise ValueError(
                    f"Multiple months found for year {year} ({sorted(matching_months)}). "
                    "Please specify month using --month or --period."
                )
        else:
            detected_year, detected_month = max(periods)
            year, month = detected_year, detected_month
            logger.info(f"Auto-selected latest period found in directory: {detected_month:02d}/{detected_year}")

    # Filter dates to matching month & year
    target_dates = [d for d in files_by_date.keys() if d.month == month and d.year == year]
    if not target_dates:
        month_name = datetime.date(year, month, 1).strftime("%B")
        raise ValueError(f"No statement/slip files found for {month_name} {year} in {directory}")

    target_dates.sort()
    ordered_paths: List[Path] = []

    for d in target_dates:
        day_files = files_by_date[d]
        # 1. Bank report
        bank_file = next((f for f in day_files if "bank" in f.name.lower()), None)
        if bank_file:
            ordered_paths.append(bank_file)
        # 2. Deposit slip
        dep_file = next((f for f in day_files if "deposit" in f.name.lower()), None)
        if dep_file:
            ordered_paths.append(dep_file)
        # 3. Payment slip
        pay_file = next((f for f in day_files if "payment" in f.name.lower()), None)
        if pay_file:
            ordered_paths.append(pay_file)

    return ordered_paths, month, year


def generate_final_cashbook(
    input_dir: Path | str,
    output_path: Optional[Path | str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    insert_blank_page: bool = True,
    only_last_page_for_payment: bool = True,  # <-- Ensure this parameter exists
) -> Tuple[Path, int, int]:
    """
    Assemble and merge the Final Cashbook PDF document for a specified month/year.
    Sequencing:
      For each day: Bank Report -> [blank] -> Deposit Slip -> [blank] -> Payment Slip -> [blank] -> next day...
      
    Returns:
      (output_path: Path, total_documents_merged: int, total_pages_in_output: int)
    """
    ordered_paths, detected_month, detected_year = get_cashbook_ordered_pdfs(
        input_dir=input_dir,
        month=month,
        year=year,
    )

    in_dir = Path(input_dir)
    if output_path:
        out_file = Path(output_path)
        if not out_file.is_absolute() and not str(out_file).startswith((".", "/")):
            out_file = in_dir / out_file
    else:
        month_name = datetime.date(detected_year, detected_month, 1).strftime("%B")
        out_file = in_dir / f"Final_Cashbook_{month_name}_{detected_year}.pdf"

    return merge_statement_pdfs(
        pdf_paths=ordered_paths,
        output_path=out_file,
        insert_blank_page=insert_blank_page,
        only_last_page_for_slips=True,
        only_last_page_for_payment=only_last_page_for_payment, # <-- Passed here
    )
