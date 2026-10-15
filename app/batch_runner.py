"""Sequential batch processing runner for date-ranged statement automation.

Processes dates sequentially, enforces rate-limiting pauses, supports resuming
incomplete batches, creates detailed execution audit manifests, and handles
graceful user cancellation.
"""
from __future__ import annotations

import json
import logging
import signal
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from app.auth import SessionExpiredError
from app.client import KDMCClient
from app.config import AppConfig
from app.date_engine import DateItem, HTTPDateEngine
from app.pdf_export import (
    generate_filename,
    get_target_file_path,
    render_html_to_pdf,
    save_debug_html,
    save_pdf_bytes,
    validate_pdf_data,
)
from app.report_parser import ReportParser, ReportValidationResult

logger = logging.getLogger("flash_automator.batch")


@dataclass
class DateResult:
    """Audit record for a single processed date."""
    date: str
    status: str  # "SUCCESS", "SKIPPED", "NO_RECORDS", "ERROR", "CANCELLED"
    output_file: Optional[str] = None
    record_count: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


class BatchRunner:
    """
    Orchestrates batch execution over a configured sequence of dates.
    """

    def __init__(
        self,
        client: KDMCClient,
        config: AppConfig,
        date_engine: HTTPDateEngine,
        resume: bool = True,
        progress_callback: Optional[Callable[[int, int, DateResult], None]] = None,
    ) -> None:
        self.client = client
        self.config = config
        self.date_engine = date_engine
        self.resume = resume
        self.progress_callback = progress_callback
        self._cancelled = False

        # Register signal handlers for clean cancellation
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        logger.warning("Cancellation requested by user. Completing current item and halting gracefully...")
        self._cancelled = True

    def cancel(self) -> None:
        """Programmatically request cancellation."""
        self._cancelled = True

    def process_single_date(self, item: DateItem) -> DateResult:
        """
        Process a single date: fetch, validate, export PDF, and record audit status.
        """
        start_time = time.time()
        prefix = self.config.filename_prefix
        target_path, already_exists = get_target_file_path(
            output_dir=self.config.output_dir,
            date_input=item.date,
            overwrite=self.config.overwrite,
            prefix=prefix,
        )

        # Check resume condition
        if already_exists and self.resume and not self.config.overwrite:
            # Check existing file is valid
            try:
                with open(target_path, "rb") as f:
                    pdf_bytes = f.read()
                is_valid, _, page_count = validate_pdf_data(pdf_bytes)
                if is_valid:
                    duration = time.time() - start_time
                    logger.info(f"[{item.date_str}] Already exists and valid: {target_path.name} (Skipping).")
                    return DateResult(
                        date=item.date_str,
                        status="SKIPPED",
                        output_file=str(target_path),
                        record_count=0,
                        duration_seconds=round(duration, 2),
                    )
            except Exception as e:
                logger.warning(f"Existing file {target_path} corrupted or unreadable ({e}). Will re-download.")

        # 1. Submit report request
        try:
            resp = self.client.fetch_report(item.date_str)
        except SessionExpiredError as e:
            duration = time.time() - start_time
            logger.error(f"[{item.date_str}] Session expired: {e}")
            return DateResult(
                date=item.date_str,
                status="ERROR",
                duration_seconds=round(duration, 2),
                error_message=f"Session expired: {e}",
            )
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{item.date_str}] Request failed: {e}")
            return DateResult(
                date=item.date_str,
                status="ERROR",
                duration_seconds=round(duration, 2),
                error_message=str(e),
            )

        # BIRT report workflow (Deposit Slip / Payment Slip - Direct BIRT vector PDF)
        if self.config.is_birt_report:
            if resp.content.startswith(b"%PDF-"):
                try:
                    pdf_path = save_pdf_bytes(
                        resp.content,
                        target_path,
                        last_page_only=self.config.last_page_only,
                    )
                    with open(pdf_path, "rb") as f:
                        saved_bytes = f.read()
                    is_valid, _, page_count = validate_pdf_data(saved_bytes)
                    duration = time.time() - start_time
                    logger.info(
                        f"[{item.date_str}] Success! Generated {pdf_path.name} "
                        f"({page_count} page{'s' if page_count != 1 else ''}, {round(duration, 2)}s)"
                    )
                    return DateResult(
                        date=item.date_str,
                        status="SUCCESS",
                        output_file=str(pdf_path),
                        record_count=page_count,
                        duration_seconds=round(duration, 2),
                    )
                except Exception as e:
                    duration = time.time() - start_time
                    logger.error(f"[{item.date_str}] PDF save error: {e}")
                    return DateResult(
                        date=item.date_str,
                        status="ERROR",
                        duration_seconds=round(duration, 2),
                        error_message=f"Save failed: {e}",
                    )
            else:
                duration = time.time() - start_time
                error_text = resp.text[:200] if hasattr(resp, "text") else "Invalid response"
                logger.error(f"[{item.date_str}] Expected PDF response but got: {error_text}")
                return DateResult(
                    date=item.date_str,
                    status="ERROR",
                    duration_seconds=round(duration, 2),
                    error_message=f"Response does not contain valid PDF magic bytes: {error_text}",
                )

        # Bank Account Statement workflow (HTML table -> WeasyPrint PDF)
        # Save debug HTML if enabled
        if self.config.save_html:
            debug_file = save_debug_html(resp.text, self.config.debug_dir, item.date_str)
            logger.debug(f"Saved raw debug HTML to: {debug_file}")

        # 2. Validate response
        val_res = ReportParser.validate_response(resp.text)
        if not val_res.is_valid:
            duration = time.time() - start_time
            logger.warning(f"[{item.date_str}] Validation failed: {val_res.error_message}")
            return DateResult(
                date=item.date_str,
                status="ERROR",
                duration_seconds=round(duration, 2),
                error_message=val_res.error_message,
            )

        if val_res.is_empty:
            duration = time.time() - start_time
            logger.info(f"[{item.date_str}] No records present on server for this date.")
            return DateResult(
                date=item.date_str,
                status="NO_RECORDS",
                duration_seconds=round(duration, 2),
                error_message=val_res.error_message,
            )

        # 3. Extract and export PDF
        try:
            clean_html = ReportParser.extract_clean_printable_html(resp.text)
            pdf_path = render_html_to_pdf(clean_html, target_path)
            duration = time.time() - start_time
            logger.info(
                f"[{item.date_str}] Success! Generated {pdf_path.name} "
                f"({val_res.record_count} records, {round(duration, 2)}s)"
            )
            return DateResult(
                date=item.date_str,
                status="SUCCESS",
                output_file=str(pdf_path),
                record_count=val_res.record_count,
                duration_seconds=round(duration, 2),
            )
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{item.date_str}] PDF export error: {e}")
            return DateResult(
                date=item.date_str,
                status="ERROR",
                duration_seconds=round(duration, 2),
                error_message=f"Export failed: {e}",
            )

    def run(self) -> List[DateResult]:
        """
        Execute the batch workflow across all dates in date_engine.
        """
        items_to_run = self.date_engine.get_included_items()
        total_items = len(items_to_run)
        logger.info(f"Starting batch runner for {total_items} target dates (Delay: {self.config.request_delay}s)...")

        results: List[DateResult] = []

        # Refresh CSRF token if session manager doesn't have one
        if not self.client.session_manager.csrf_token:
            logger.info("Initializing session and fetching CSRF token...")
            try:
                self.client.refresh_csrf_token()
            except SessionExpiredError as e:
                logger.error(f"Cannot start batch: {e}")
                return results

        for index, item in enumerate(items_to_run, start=1):
            if self._cancelled:
                logger.warning("Batch execution halted due to user cancellation.")
                for remaining_item in items_to_run[index - 1:]:
                    results.append(DateResult(
                        date=remaining_item.date_str,
                        status="CANCELLED",
                        error_message="Batch cancelled by user",
                    ))
                break

            logger.info(f"[{index}/{total_items}] Processing date: {item.date_str} ({item.weekday_name})...")
            res = self.process_single_date(item)
            results.append(res)

            if self.progress_callback:
                self.progress_callback(index, total_items, res)

            # If authentication failure, halt batch immediately
            if res.status == "ERROR" and res.error_message and "Session expired" in res.error_message:
                logger.error("Authentication expired during batch. Halting further requests.")
                break

            # Polite inter-request delay
            if index < total_items and not self._cancelled:
                time.sleep(self.config.request_delay)

        self._save_manifest(results)
        return results

    def _save_manifest(self, results: List[DateResult]) -> Path:
        """Write execution manifest to output directory for auditability."""
        manifest_file = self.config.output_dir / "execution_manifest.json"
        data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_processed": len(results),
            "success_count": sum(1 for r in results if r.status == "SUCCESS"),
            "skipped_count": sum(1 for r in results if r.status == "SKIPPED"),
            "no_records_count": sum(1 for r in results if r.status == "NO_RECORDS"),
            "error_count": sum(1 for r in results if r.status == "ERROR"),
            "cancelled_count": sum(1 for r in results if r.status == "CANCELLED"),
            "items": [asdict(r) for r in results],
        }
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Execution manifest saved to: {manifest_file}")
        return manifest_file


class CashbookRunner:
    """
    Orchestrates downloading all 3 municipal reports (Bank Statement, Deposit Slip,
    and Payment Slip) for every day of a calendar month, and compiles them into a
    unified Final Cashbook with 1 blank separator page between each document.
    """

    def __init__(
        self,
        client: KDMCClient,
        config: AppConfig,
        month: int,
        year: int,
        date_engine: Optional[HTTPDateEngine] = None,
        resume: bool = True,
        skip_download: bool = False,
        insert_blank_page: bool = True,
        output_file: Optional[Path | str] = None,
    ) -> None:
        self.client = client
        self.config = config
        self.month = month
        self.year = year
        self.resume = resume
        self.skip_download = skip_download
        self.insert_blank_page = insert_blank_page
        self.output_file = output_file
        self._cancelled = False

        import calendar
        last_day = calendar.monthrange(year, month)[1]
        start_str = f"01/{month:02d}/{year}"
        end_str = f"{last_day:02d}/{month:02d}/{year}"

        self.date_engine = date_engine or HTTPDateEngine(
            start_date=start_str,
            end_date=end_str,
        )

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        logger.warning(f"Cashbook runner received interrupt signal {signum}. Halting gracefully...")
        self._cancelled = True

    def _is_file_valid(self, path: Path) -> bool:
        """Check if PDF file exists and is valid."""
        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                content = f.read()
            is_valid, _, page_count = validate_pdf_data(content)
            return is_valid and page_count >= 1
        except Exception:
            return False

    def _fetch_and_save_bank_statement(self, item: DateItem, target_path: Path) -> bool:
        """Fetch and render Bank Account Statement."""
        try:
            resp = self.client.fetch_bank_statement(item.date_str)
            val_res = ReportParser.validate_response(resp.text)
            if val_res.is_empty:
                logger.info(f"  -> [1/3] Bank Statement: No account records on portal for {item.date_str}.")
                return False
            if not val_res.is_valid:
                logger.warning(f"  -> [1/3] Bank Statement: Notice for {item.date_str} ({val_res.error_message})")
                return False
            clean_html = ReportParser.extract_clean_printable_html(resp.text)
            render_html_to_pdf(clean_html, target_path)
            logger.info(f"  -> [1/3] Bank Statement: Saved {target_path.name} ({val_res.record_count} accounts)")
            return True
        except SessionExpiredError as e:
            logger.error(f"  -> [1/3] Bank Statement: Session expired ({e}). Set valid KDMC_SESSION_COOKIE in .env.")
            return False
        except Exception as e:
            logger.error(f"  -> [1/3] Bank Statement: Failed for {item.date_str}: {e}")
            return False

    def _fetch_and_save_deposit_slip(self, item: DateItem, target_path: Path) -> bool:
        """Fetch Deposit Slip and save 1-page summary."""
        try:
            resp = self.client.fetch_deposit_slip(item.date_str)
            if resp.content.startswith(b"%PDF-"):
                save_pdf_bytes(resp.content, target_path, last_page_only=True)
                logger.info(f"  -> [2/3] Deposit Slip:   Saved {target_path.name} (1-page summary)")
                return True
            else:
                logger.error(f"  -> [2/3] Deposit Slip:   Unexpected response: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"  -> [2/3] Deposit Slip:   Failed for {item.date_str}: {e}")
            return False

    def _fetch_and_save_payment_slip(self, item: DateItem, target_path: Path) -> bool:
        """Fetch Payment Slip and save 1-page summary."""
        try:
            resp = self.client.fetch_payment_slip(item.date_str)
            if resp.content.startswith(b"%PDF-"):
                save_pdf_bytes(resp.content, target_path, last_page_only=True)
                logger.info(f"  -> [3/3] Payment Slip:   Saved {target_path.name} (1-page summary)")
                return True
            else:
                logger.error(f"  -> [3/3] Payment Slip:   Unexpected response: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"  -> [3/3] Payment Slip:   Failed for {item.date_str}: {e}")
            return False

    def run(self) -> Tuple[Optional[Path], int, int]:
        """
        Execute full-month Cashbook workflow:
        1. Downloads missing Bank Statements, Deposit Slips, and Payment Slips for every date.
        2. Compiles the Final Cashbook PDF in exact order with blank pages in between.
        Returns: (cashbook_path, total_reports_merged, total_pages)
        """
        import calendar
        month_name = calendar.month_name[self.month]
        from app.pdf_merge import organize_month_pdfs

        out_dir = organize_month_pdfs(
            input_dir=self.config.output_dir,
            month=self.month,
            year=self.year,
        )

        items = self.date_engine.get_all_items()
        included_items = [it for it in items if it.is_included]
        total_days = len(included_items)

        logger.info("=" * 70)
        logger.info(f"  FLASH AUTOMATOR: FULL MONTH CASHBOOK WORKFLOW ({month_name} {self.year})")
        logger.info(f"  Period: {self.month:02d}/{self.year} ({total_days} scheduled days)")
        logger.info("  Order per Day: Bank Statement -> Deposit Slip -> Payment Slip")
        logger.info("  Branch: Ward 4 / HO Main Branch (Enforced for all reports)")
        logger.info("=" * 70)

        if not self.skip_download:
            # Refresh CSRF token for BAS if session cookie configured
            if self.client.session_manager.has_session_cookie and not self.client.session_manager.csrf_token:
                logger.info("Initializing session and synchronizing CSRF token with portal...")
                self.client.refresh_csrf_token()

            day_idx = 1
            for item in items:
                if self._cancelled:
                    logger.warning("Cashbook processing halted due to cancellation.")
                    break

                if not item.is_included:
                    logger.info(f"[{item.date_str}] Skipped date: {item.skip_reason}")
                    continue

                logger.info(f"[{day_idx:02d}/{total_days:02d}] Processing {item.date_str} ({item.weekday_name}):")

                # Paths
                bank_path = out_dir / generate_filename(item.date, prefix="BankStatement")
                dep_path = out_dir / generate_filename(item.date, prefix="DepositSlip")
                pay_path = out_dir / generate_filename(item.date, prefix="PaymentSlip")

                # 1. Bank Statement
                bank_needed = self.config.overwrite or not (self.resume and self._is_file_valid(bank_path))
                if not bank_needed:
                    logger.info(f"  -> [1/3] Bank Statement: Already downloaded ({bank_path.name})")
                else:
                    logger.info(f"  -> [1/3] Bank Statement: Requesting from portal (HO Main Branch)...")
                    downloaded = self._fetch_and_save_bank_statement(item, bank_path)
                    if downloaded:
                        time.sleep(self.config.request_delay)

                # 2. Deposit Slip
                dep_needed = self.config.overwrite or not (self.resume and self._is_file_valid(dep_path))
                if not dep_needed:
                    logger.info(f"  -> [2/3] Deposit Slip:   Already downloaded ({dep_path.name})")
                else:
                    logger.info(f"  -> [2/3] Deposit Slip:   Requesting from BIRT server (HO Main Branch)...")
                    downloaded = self._fetch_and_save_deposit_slip(item, dep_path)
                    if downloaded:
                        time.sleep(self.config.request_delay)

                # 3. Payment Slip
                pay_needed = self.config.overwrite or not (self.resume and self._is_file_valid(pay_path))
                if not pay_needed:
                    logger.info(f"  -> [3/3] Payment Slip:   Already downloaded ({pay_path.name})")
                else:
                    logger.info(f"  -> [3/3] Payment Slip:   Requesting from BIRT server (HO Main Branch)...")
                    downloaded = self._fetch_and_save_payment_slip(item, pay_path)
                    if downloaded:
                        time.sleep(self.config.request_delay)

                day_idx += 1

        # Step 2: Merge each report type separately for this month.
        from app.pdf_merge import generate_monthly_report_merges

        for merged_path, report_count, page_count in generate_monthly_report_merges(
            input_dir=out_dir,
            month=self.month,
            year=self.year,
            insert_blank_page=self.insert_blank_page,
        ):
            logger.info(
                "Generated monthly report merge: %s (%s reports, %s pages)",
                merged_path,
                report_count,
                page_count,
            )

        # Step 3: Compile Final Cashbook
        logger.info("=" * 70)
        logger.info(f"  ASSEMBLING FINAL CASHBOOK: {month_name} {self.year}")
        logger.info("  Sequence: Bank Statement -> [blank] -> Deposit Slip -> [blank] -> Payment Slip -> [blank]")
        logger.info("=" * 70)

        from app.pdf_merge import generate_final_cashbook
        cashbook_path, total_reports, total_pages = generate_final_cashbook(
            input_dir=out_dir,
            output_path=self.output_file,
            month=self.month,
            year=self.year,
            insert_blank_page=self.insert_blank_page,
        )

        logger.info(f"Successfully generated Final Cashbook: {cashbook_path}")
        logger.info(f"Total Daily Reports Merged: {total_reports}")
        logger.info(f"Total Pages in Cashbook:    {total_pages}")
        logger.info(f"Cashbook File Size:         {cashbook_path.stat().st_size:,} bytes")
        return cashbook_path, total_reports, total_pages
