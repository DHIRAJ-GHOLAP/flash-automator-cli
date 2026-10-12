"""Command Line Interface (CLI) for KDMC MyNet HTTP Report Automation.

Provides commands for single-date proof of concept testing, batch report generation,
and date iteration previewing.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from app.auth import SessionExpiredError, SessionManager
from app.batch_runner import BatchRunner, CashbookRunner
from app.client import KDMCClient
from app.config import AppConfig, load_config
from app.date_engine import HTTPDateEngine, parse_date_string
from app.logging_config import setup_logging
from app.pdf_export import (
    get_target_file_path,
    render_html_to_pdf,
    save_debug_html,
    save_pdf_bytes,
    validate_pdf_data,
)
from app.report_parser import ReportParser

logger = logging.getLogger("flash_automator.cli")


def cmd_test_date(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute Phase 3: Single-date proof of concept."""
    logger.info(f"--- Running Single-Date Proof of Concept for {args.date} ---")

    # Validate date format
    try:
        parsed_date = parse_date_string(args.date)
        date_str = parsed_date.strftime("%d/%m/%Y")
    except ValueError as e:
        logger.error(f"Invalid date argument: {e}")
        return 1

    # Override config options from CLI flags if given
    if getattr(args, "report_type", None):
        config.report_type_code = args.report_type
    if args.output_dir:
        config.output_dir = Path(args.output_dir)
    if args.save_html:
        config.save_html = True
    if args.overwrite:
        config.overwrite = True
    if getattr(args, "all_pages", False):
        config.last_page_only = False

    session_mgr = SessionManager(
        session_cookie=config.session_cookie,
        csrf_token=config.csrf_token,
    )

    if not session_mgr.has_session_cookie:
        logger.warning(
            "No session cookie (JSESSIONID) configured in environment or .env. "
            "Municipal portal requests may fail or redirect to Login.html. "
            "Set KDMC_SESSION_COOKIE in .env to use an authorized session."
        )

    client = KDMCClient(config=config, session_manager=session_mgr)

    # 1. Acquire / verify CSRF token (only needed for MainetService BAS forms)
    if not config.is_birt_report and not session_mgr.csrf_token:
        logger.info("Attempting to acquire CSRF token from portal...")
        client.refresh_csrf_token()

    # 2. Check target output path and duplicate protection
    prefix = config.filename_prefix
    target_path, already_exists = get_target_file_path(
        output_dir=config.output_dir,
        date_input=parsed_date,
        overwrite=config.overwrite,
        prefix=prefix,
    )
    if already_exists and not config.overwrite:
        logger.warning(
            f"File already exists: {target_path}. "
            "Use --overwrite to re-download and replace."
        )
        return 0

    # 3. Submit request
    try:
        if config.is_deposit_slip:
            report_label = "Deposit Slip PDF"
        elif config.is_payment_slip:
            report_label = "Payment Slip PDF"
        else:
            report_label = "Bank Statement POST"
        logger.info(f"Submitting {report_label} request for date {date_str}...")
        resp = client.fetch_report(date_str)
    except SessionExpiredError as e:
        logger.error(f"Session Authentication Failed: {e}")
        return 2
    except Exception as e:
        logger.error(f"HTTP Request Failed: {e}")
        return 1

    logger.info(f"HTTP Status: {resp.status_code} ({len(resp.content)} bytes received)")

    # 4. BIRT report workflow (Deposit Slip / Payment Slip - Direct BIRT vector PDF)
    if config.is_birt_report:
        if resp.content.startswith(b"%PDF-"):
            try:
                pdf_path = save_pdf_bytes(
                    resp.content,
                    target_path,
                    last_page_only=config.last_page_only,
                )
                with open(pdf_path, "rb") as f:
                    saved_bytes = f.read()
                is_valid, reason, page_count = validate_pdf_data(saved_bytes)
                report_name = "Deposit Slip" if config.is_deposit_slip else "Payment Slip"
                logger.info(f"Successfully generated {report_name} PDF: {pdf_path}")
                logger.info(f"Pages: {page_count} | Size: {pdf_path.stat().st_size:,} bytes | Destination: {pdf_path.resolve()}")
                logger.info("--- Single-date test completed successfully ---")
                return 0
            except Exception as e:
                logger.error(f"{config.filename_prefix} Save Error: {e}")
                return 1
        else:
            logger.error(f"Expected PDF response but received non-PDF payload: {resp.text[:300]}")
            return 1

    # 5. Bank Account Statement workflow (HTML table -> WeasyPrint PDF)
    if config.save_html:
        saved_debug = save_debug_html(resp.text, config.debug_dir, date_str)
        logger.info(f"Saved raw response HTML to: {saved_debug}")

    # Validate response structure
    val_res = ReportParser.validate_response(resp.text)
    if not val_res.is_valid:
        logger.error(f"Response Validation Failed: {val_res.error_message}")
        return 1

    if val_res.is_empty:
        logger.info(
            f"Result: Date {date_str} returned no bank statement records "
            f"({val_res.error_message})"
        )
        return 0

    logger.info(
        f"Validation Passed! Found valid report table titled '{val_res.title}' "
        f"with {val_res.record_count} account balance rows."
    )

    # Extract clean HTML and generate PDF
    try:
        clean_html = ReportParser.extract_clean_printable_html(resp.text)
        pdf_path = render_html_to_pdf(clean_html, target_path)
        logger.info(f"Successfully generated PDF report: {pdf_path}")
        logger.info(f"Size: {pdf_path.stat().st_size:,} bytes | Destination: {pdf_path.resolve()}")
    except Exception as e:
        logger.error(f"PDF Export Failed: {e}")
        return 1

    logger.info("--- Single-date test completed successfully ---")
    return 0


def cmd_batch(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute Phase 6: Sequential Batch Runner."""
    if getattr(args, "report_type", None):
        config.report_type_code = args.report_type
    if getattr(args, "all_pages", False):
        config.last_page_only = False

    if config.is_deposit_slip:
        report_desc = "Deposit Slips"
    elif config.is_payment_slip:
        report_desc = "Payment Slips"
    else:
        report_desc = "Bank Statements"
    logger.info(f"--- Running Batch {report_desc} Automation from {args.start} to {args.end} ---")

    # Override config options
    if args.output_dir:
        config.output_dir = Path(args.output_dir)
    if args.delay is not None:
        config.request_delay = float(args.delay)
    if args.save_html:
        config.save_html = True
    if args.overwrite:
        config.overwrite = True

    # Parse exclusions
    excluded_dates = []
    if args.exclude_dates:
        excluded_dates = [d.strip() for d in args.exclude_dates.split(",") if d.strip()]

    excluded_weekdays = set()
    if args.skip_sundays:
        excluded_weekdays.add(6)
    if args.skip_saturdays:
        excluded_weekdays.add(5)

    try:
        date_engine = HTTPDateEngine(
            start_date=args.start,
            end_date=args.end,
            weekdays_only=args.weekdays_only,
            exclude_weekdays=sorted(list(excluded_weekdays)) if excluded_weekdays else None,
            exclude_dates=excluded_dates if excluded_dates else None,
        )
    except ValueError as e:
        logger.error(f"Invalid date range or parameters: {e}")
        return 1

    session_mgr = SessionManager(
        session_cookie=config.session_cookie,
        csrf_token=config.csrf_token,
    )
    client = KDMCClient(config=config, session_manager=session_mgr)

    if not config.is_birt_report and not session_mgr.csrf_token:
        client.refresh_csrf_token()

    runner = BatchRunner(
        client=client,
        config=config,
        date_engine=date_engine,
        resume=not args.no_resume,
    )

    results = runner.run()

    successes = sum(1 for r in results if r.status == "SUCCESS")
    skipped = sum(1 for r in results if r.status == "SKIPPED")
    no_records = sum(1 for r in results if r.status == "NO_RECORDS")
    errors = sum(1 for r in results if r.status == "ERROR")
    cancelled = sum(1 for r in results if r.status == "CANCELLED")

    logger.info("--- Batch Execution Summary ---")
    logger.info(f"Total Evaluated: {len(results)}")
    logger.info(f"Successful:      {successes}")
    logger.info(f"Skipped/Resumed: {skipped}")
    logger.info(f"No Records:      {no_records}")
    logger.info(f"Errors:          {errors}")
    if cancelled:
        logger.info(f"Cancelled:       {cancelled}")

    return 0 if errors == 0 else 1


def cmd_generate_dates(args: argparse.Namespace) -> int:
    """Preview evaluated date schedule."""
    excluded_dates = []
    if args.exclude_dates:
        excluded_dates = [d.strip() for d in args.exclude_dates.split(",") if d.strip()]

    excluded_weekdays = set()
    if args.skip_sundays:
        excluded_weekdays.add(6)
    if args.skip_saturdays:
        excluded_weekdays.add(5)

    try:
        date_engine = HTTPDateEngine(
            start_date=args.start,
            end_date=args.end,
            weekdays_only=args.weekdays_only,
            exclude_weekdays=sorted(list(excluded_weekdays)) if excluded_weekdays else None,
            exclude_dates=excluded_dates if excluded_dates else None,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    all_items = date_engine.get_all_items()
    included_count = sum(1 for item in all_items if item.is_included)
    skipped_count = len(all_items) - included_count

    print(f"Date Iteration Preview ({args.start} to {args.end}):")
    print(f"{'#':<4} {'Date':<12} {'Day':<11} {'Status':<10} {'Reason'}")
    print("-" * 65)

    for i, item in enumerate(all_items, 1):
        status = "INCLUDED" if item.is_included else "SKIPPED"
        reason = item.skip_reason or ""
        print(f"{i:<4} {item.date_str:<12} {item.weekday_name:<11} {status:<10} {reason}")

    print("-" * 65)
from app.pdf_merge import (
    MONTH_NAMES,
    generate_final_cashbook,
    get_sorted_statement_pdfs,
    merge_statement_pdfs,
    parse_period_string,
)


def cmd_merge(args: argparse.Namespace, config: AppConfig) -> int:
    """Merge all generated statement/slip PDFs with one empty page in between."""
    input_dir = Path(args.input_dir) if args.input_dir else config.output_dir
    prefix = getattr(args, "prefix", None)

    logger.info(f"--- Merging PDF Reports from {input_dir} (Prefix: {prefix or 'Auto'}) ---")

    try:
        pdf_files = get_sorted_statement_pdfs(input_dir, prefix=prefix)
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    if not pdf_files:
        filter_msg = f" matching prefix '{prefix}'" if prefix else ""
        logger.error(f"No statement PDF files found in directory{filter_msg}: {input_dir}")
        return 1

    logger.info(f"Found {len(pdf_files)} PDF statements to merge in chronological order:")
    for i, f in enumerate(pdf_files, 1):
        logger.info(f"  {i:>2}. {f.name}")

    if args.output_file:
        out_path = Path(args.output_file)
        if not out_path.is_absolute() and not str(out_path).startswith((".", "/")):
            out_path = input_dir / out_path
    else:
        first_name = pdf_files[0].name.lower()
        if (prefix and "deposit" in prefix.lower()) or "depositslip" in first_name:
            out_path = input_dir / "Merged_DepositSlips.pdf"
        elif (prefix and "payment" in prefix.lower()) or "paymentslip" in first_name:
            out_path = input_dir / "Merged_PaymentSlips.pdf"
        else:
            out_path = input_dir / "Merged_BankStatements.pdf"

    insert_blank = not args.no_blank_page
    logger.info(
        f"Blank separator page between PDFs: "
        f"{'ENABLED (1 blank page between PDFs)' if insert_blank else 'DISABLED'}"
    )

    try:
        final_path, count, total_pages = merge_statement_pdfs(
            pdf_paths=pdf_files,
            output_path=out_path,
            insert_blank_page=insert_blank,
        )
        logger.info(f"Successfully generated merged PDF: {final_path}")
        logger.info(f"Total Statements Merged: {count}")
        logger.info(f"Total Pages in Output:   {total_pages}")
        logger.info(f"Merged File Size:        {final_path.stat().st_size:,} bytes")
        return 0
    except Exception as e:
        logger.error(f"Failed to merge PDFs: {e}")
        return 1


def cmd_cashbook(args: argparse.Namespace, config: AppConfig) -> int:
    """Generate Final Cashbook PDF by downloading missing reports and assembling them with 1 blank page in between."""
    import calendar

    # Output directory
    target_dir = getattr(args, "output_dir", None) or getattr(args, "input_dir", None)
    if target_dir:
        config.output_dir = Path(target_dir)

    if getattr(args, "delay", None) is not None:
        config.request_delay = float(args.delay)
    if getattr(args, "overwrite", False):
        config.overwrite = True

    month = None
    year = None

    if getattr(args, "period", None):
        try:
            month, year = parse_period_string(args.period)
        except ValueError as e:
            logger.error(str(e))
            return 1
    else:
        if getattr(args, "month", None):
            raw_month = str(args.month).strip()
            if raw_month.isdigit():
                month = int(raw_month)
            elif raw_month.lower() in MONTH_NAMES:
                month = MONTH_NAMES[raw_month.lower()]
            else:
                logger.error(f"Invalid month argument: '{args.month}'")
                return 1
        if getattr(args, "year", None):
            try:
                year = int(args.year)
            except ValueError:
                logger.error(f"Invalid year argument: '{args.year}'")
                return 1

    insert_blank = not getattr(args, "no_blank_page", False)
    skip_download = getattr(args, "skip_download", False)

    # If period/month/year not specified but skip_download requested, allow auto-detection from existing files
    if month is None or year is None:
        if skip_download:
            try:
                final_path, count, total_pages = generate_final_cashbook(
                    input_dir=config.output_dir,
                    output_path=args.output_file,
                    month=month,
                    year=year,
                    insert_blank_page=insert_blank,
                )
                logger.info(f"Successfully generated Final Cashbook: {final_path}")
                logger.info(f"Total Daily Reports Merged: {count}")
                logger.info(f"Total Pages in Cashbook:    {total_pages}")
                logger.info(f"Cashbook File Size:         {final_path.stat().st_size:,} bytes")
                return 0
            except Exception as e:
                logger.error(f"Failed to generate Final Cashbook: {e}")
                return 1
        else:
            logger.error("Please specify --period (e.g. '07/2023') or both --month and --year.")
            return 1

    # Date range for the entire month
    last_day = calendar.monthrange(year, month)[1]
    start_date = f"01/{month:02d}/{year}"
    end_date = f"{last_day:02d}/{month:02d}/{year}"

    # Exclusions
    excluded_dates = []
    if getattr(args, "exclude_dates", None):
        excluded_dates = [d.strip() for d in args.exclude_dates.split(",") if d.strip()]

    excluded_weekdays = set()
    if getattr(args, "skip_sundays", False):
        excluded_weekdays.add(6)
    if getattr(args, "skip_saturdays", False):
        excluded_weekdays.add(5)

    try:
        date_engine = HTTPDateEngine(
            start_date=start_date,
            end_date=end_date,
            weekdays_only=getattr(args, "weekdays_only", False),
            exclude_weekdays=sorted(list(excluded_weekdays)) if excluded_weekdays else None,
            exclude_dates=excluded_dates if excluded_dates else None,
        )
    except ValueError as e:
        logger.error(f"Invalid date range or parameters: {e}")
        return 1

    session_mgr = SessionManager(
        session_cookie=config.session_cookie,
        csrf_token=config.csrf_token,
    )
    client = KDMCClient(config=config, session_manager=session_mgr)

    runner = CashbookRunner(
        client=client,
        config=config,
        month=month,
        year=year,
        date_engine=date_engine,
        resume=not getattr(args, "overwrite", False),
        skip_download=skip_download,
        insert_blank_page=insert_blank,
        output_file=args.output_file,
    )

    try:
        final_path, count, total_pages = runner.run()
        if final_path:
            return 0
        return 1
    except Exception as e:
        logger.error(f"Cashbook generation failed: {e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="flash-automator",
        description="Flash Automator: KDMC MyNet Bank Account Statement HTTP Automation",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Path to custom .env configuration file",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: test-date
    p_test = subparsers.add_parser("test-date", help="Execute single-date proof of concept")
    p_test.add_argument(
        "--date",
        type=str,
        required=True,
        help="Date to generate statement for (e.g. 10/10/2026)",
    )
    p_test.add_argument(
        "--report-type",
        type=str,
        default=None,
        help="Report type code: 'bas' (Bank Account Statement), 'deposit-slip', or 'payment-slip'",
    )
    p_test.add_argument(
        "--all-pages",
        action="store_true",
        help="Download all pages instead of only the last summary page for deposit/payment slips",
    )
    p_test.add_argument(
        "--save-html",
        action="store_true",
        help="Save raw response HTML to debug directory",
    )
    p_test.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save generated PDF (default: ./output)",
    )
    p_test.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output PDF if present",
    )

    # Subcommand: batch
    p_batch = subparsers.add_parser("batch", help="Execute sequential batch report generation")
    p_batch.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date in DD/MM/YYYY format (e.g. 01/10/2026)",
    )
    p_batch.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date in DD/MM/YYYY format (e.g. 31/10/2026)",
    )
    p_batch.add_argument(
        "--report-type",
        type=str,
        default=None,
        help="Report type code: 'bas' (Bank Account Statement), 'deposit-slip', or 'payment-slip'",
    )
    p_batch.add_argument(
        "--all-pages",
        action="store_true",
        help="Download all pages instead of only the last summary page for deposit/payment slips",
    )
    p_batch.add_argument(
        "--weekdays-only",
        action="store_true",
        help="Skip Saturdays and Sundays",
    )
    p_batch.add_argument(
        "--skip-sundays",
        action="store_true",
        help="Skip Sundays",
    )
    p_batch.add_argument(
        "--skip-saturdays",
        action="store_true",
        help="Skip Saturdays",
    )
    p_batch.add_argument(
        "--exclude-dates",
        type=str,
        default=None,
        help="Comma-separated dates to exclude (e.g. 15/10/2026,24/10/2026)",
    )
    p_batch.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Polite pause delay between requests in seconds (default: 1.5)",
    )
    p_batch.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip dates that already have valid PDFs",
    )
    p_batch.add_argument(
        "--save-html",
        action="store_true",
        help="Save raw HTML response files into debug folder",
    )
    p_batch.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save generated PDFs",
    )
    p_batch.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )

    # Subcommand: generate-dates
    p_gen = subparsers.add_parser("generate-dates", help="Preview date schedule without HTTP calls")
    p_gen.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (DD/MM/YYYY)",
    )
    p_gen.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date (DD/MM/YYYY)",
    )
    p_gen.add_argument(
        "--weekdays-only",
        action="store_true",
        help="Skip Saturdays and Sundays",
    )
    p_gen.add_argument(
        "--skip-sundays",
        action="store_true",
        help="Skip Sundays",
    )
    p_gen.add_argument(
        "--skip-saturdays",
        action="store_true",
        help="Skip Saturdays",
    )
    p_gen.add_argument(
        "--exclude-dates",
        type=str,
        default=None,
        help="Comma-separated dates to exclude",
    )

    # Subcommand: merge
    p_merge = subparsers.add_parser(
        "merge",
        help="Merge all statement PDFs in chronological order with 1 blank page in between",
    )
    p_merge.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help="Directory containing statement PDFs (default: ./output)",
    )
    p_merge.add_argument(
        "--output-file",
        type=str,
        default=None,
        help="Destination merged PDF filename or path (default: Merged_BankStatements.pdf, Merged_DepositSlips.pdf, or Merged_PaymentSlips.pdf)",
    )
    p_merge.add_argument(
        "--prefix",
        type=str,
        default=None,
        help="Filter statements by filename prefix (e.g. 'DepositSlip', 'PaymentSlip', or 'BankStatement')",
    )
    p_merge.add_argument(
        "--no-blank-page",
        action="store_true",
        help="Do not insert a blank separator page between statements",
    )

    # Subcommand: cashbook
    p_cash = subparsers.add_parser(
        "cashbook",
        help="Assemble Final Cashbook (Bank Report -> Deposit Slip -> Payment Slip per day with 1 blank page in between)",
    )
    p_cash.add_argument(
        "--period",
        type=str,
        default=None,
        help="Month and year period (e.g. '07/2023', 'July 2023', or '07-2023')",
    )
    p_cash.add_argument(
        "--month",
        type=str,
        default=None,
        help="Month number (1-12) or name (e.g. '7' or 'July')",
    )
    p_cash.add_argument(
        "--year",
        type=int,
        default=None,
        help="Four-digit year (e.g. 2023)",
    )
    p_cash.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help="Directory containing statement PDFs (default: ./output)",
    )
    p_cash.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save generated PDFs (default: ./output)",
    )
    p_cash.add_argument(
        "--output-file",
        type=str,
        default=None,
        help="Destination merged PDF filename or path (default: Final_Cashbook_{Month}_{Year}.pdf)",
    )
    p_cash.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading and compile immediately from existing output files",
    )
    p_cash.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite and re-download existing files instead of resuming",
    )
    p_cash.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Polite pause delay between requests in seconds (default: 1.5)",
    )
    p_cash.add_argument(
        "--weekdays-only",
        action="store_true",
        help="Skip Saturdays and Sundays",
    )
    p_cash.add_argument(
        "--skip-sundays",
        action="store_true",
        help="Skip Sundays",
    )
    p_cash.add_argument(
        "--skip-saturdays",
        action="store_true",
        help="Skip Saturdays",
    )
    p_cash.add_argument(
        "--exclude-dates",
        type=str,
        default=None,
        help="Comma-separated dates to exclude (e.g. 15/07/2023,24/07/2023)",
    )
    p_cash.add_argument(
        "--no-blank-page",
        action="store_true",
        help="Do not insert a blank separator page between reports",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "generate-dates":
        return cmd_generate_dates(args)

    config = load_config(args.env_file)

    if args.subcommand == "test-date":
        return cmd_test_date(args, config)
    elif args.subcommand == "batch":
        return cmd_batch(args, config)
    elif args.subcommand == "merge":
        return cmd_merge(args, config)
    elif args.subcommand == "cashbook":
        return cmd_cashbook(args, config)

    return 0


if __name__ == "__main__":
    sys.exit(main())
