# Flash Automator CLI

> **High-Performance Municipal Report Automation & Final Cashbook Assembly for KDMC MyNet**
> Built for Python 3.10+ and Windows 7 / 10 / 11 PowerShell.

---

## Overview

**Flash Automator CLI** automates fetching, rendering, extracting, and compiling municipal financial reports from KDMC MyNet (Kalyan Dombivli Municipal Corporation).

Unlike UI-based macro tools that simulate mouse coordinates, Flash Automator communicates directly with the municipal web servers via authenticated HTTP requests and Eclipse BIRT report endpoints:
1. **Bank Account Statements (BAS)**: Authenticated HTTP POST to `MainetService/AccountFinancialReport.html` rendered into high-fidelity A4 Landscape PDFs via WeasyPrint.
2. **Deposit Slips**: Direct vector PDF stream from `birtPA/output` (`DepositSlip_ReceiptDetailReport.rptdesign`), automatically extracting the **1-page summary** (last page).
3. **Payment Slips**: Direct vector PDF stream from `birtPA/output` (`DepositSlip_PaymentDetailReport.rptdesign`), automatically extracting the **1-page summary** (last page).
4. **Final Cashbook Compilation**: Assembles the complete monthly cashbook in exact daily sequence (`Bank Statement -> [1 blank page] -> Deposit Slip -> [1 blank page] -> Payment Slip -> [1 blank page] -> Next Day...`), formatted specifically for physical duplex (double-sided) printing.
5. **HO Main Branch Enforcement**: Automatically enforces **Ward 4 / fieldId 4** across all report endpoints.

---

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/DHIRAJ-GHOLAP/flash-automator-cli.git
cd flash-automator-cli

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration (`.env`)

Copy `.env.example` to `.env` and provide your authorized browser session cookie (`JSESSIONID`):

```bash
cp .env.example .env
```

Edit `.env`:
```ini
KDMC_BASE_URL=https://kdmc.gov.in/MainetService
KDMC_BIRT_OUTPUT_URL=https://kdmc.gov.in/birtPA/output
KDMC_SESSION_COOKIE=YOUR_JSESSIONID_FROM_BROWSER
KDMC_FIELD_ID=4
KDMC_WARD=4
KDMC_REQUEST_DELAY=1.5
KDMC_OUTPUT_DIR=./output
```

> **How to get your session cookie:**
> 1. Log in to KDMC MyNet in Chrome or Edge.
> 2. Press `F12` to open Developer Tools, go to the **Application** (or **Storage**) tab -> **Cookies** -> `https://kdmc.gov.in`.
> 3. Copy the value of `JSESSIONID` and paste it into `.env`.

---

## Commands & Usage

You can invoke the CLI using either `python3 -m app.cli <command>` or `python3 cli.py <command>`.

### 1. Full-Month Cashbook Automation (`cashbook`)

Downloads all 3 reports (Bank Statement, Deposit Slip summary, Payment Slip summary) for every day of the month with real-time status logging, and then compiles the final duplex-ready PDF:

```bash
# Run complete July 2023 cashbook workflow
python3 -m app.cli cashbook --period 07/2023

# Alternative period formats:
python3 -m app.cli cashbook --period "July 2023"
python3 -m app.cli cashbook --month 7 --year 2023

# Fast compile: assemble immediately from existing PDFs without re-downloading
python3 -m app.cli cashbook --period 07/2023 --skip-download

# Force re-download all files:
python3 -m app.cli cashbook --period 07/2023 --overwrite

# Polite rate limiting (e.g. 2.0s delay between downloads):
python3 -m app.cli cashbook --period 07/2023 --delay 2.0

# Exclude Sundays or custom dates:
python3 -m app.cli cashbook --period 07/2023 --skip-sundays --exclude-dates 15/07/2023,24/07/2023

# Generate all 12 monthly cashbooks for a year:
python3 -m app.cli cashbook --year 2023

# Assemble all 12 months from PDFs already in the output directory:
python3 -m app.cli cashbook --year 2023 --skip-download
```

Each monthly run also creates separate, month-specific merged PDFs for bank statements, deposit slips, and payment slips, alongside `Final_Cashbook_{Month}_{Year}.pdf`.
All PDFs for that period are stored together in `output/{Month}_{Year}/` (for example, `output/July_2023/`). A year run creates one folder for each month, and existing root-level PDFs are moved into the matching folder when that month is processed.

**Real-Time Output Example:**
```text
======================================================================
  FLASH AUTOMATOR: FULL MONTH CASHBOOK WORKFLOW (July 2023)
  Period: 07/2023 (31 scheduled days)
  Order per Day: Bank Statement -> Deposit Slip -> Payment Slip
  Branch: Ward 4 / HO Main Branch (Enforced for all reports)
======================================================================
[01/31] Processing 01/07/2023 (Saturday):
  -> [1/3] Bank Statement: Already downloaded (BankStatement_01-07-2023.pdf)
  -> [2/3] Deposit Slip:   Already downloaded (DepositSlip_01-07-2023.pdf)
  -> [3/3] Payment Slip:   Already downloaded (PaymentSlip_01-07-2023.pdf)
...
======================================================================
  ASSEMBLING FINAL CASHBOOK: July 2023
  Sequence: Bank Statement -> [blank] -> Deposit Slip -> [blank] -> Payment Slip -> [blank]
======================================================================
Successfully generated Final Cashbook: output/Final_Cashbook_July_2023.pdf
Total Daily Reports Merged: 93
Total Pages in Cashbook:    259
Cashbook File Size:         2,752,384 bytes
```

---

### 2. Batch Date-Range Automation (`batch`)

Run sequential batches for a specific report type across any date range:

```bash
# 1. Bank Account Statements (BAS)
python3 -m app.cli batch --start 01/07/2023 --end 31/07/2023 --report-type bas

# 2. Deposit Slips (1-page summary per date)
python3 -m app.cli batch --start 01/07/2023 --end 31/07/2023 --report-type deposit-slip

# 3. Payment Slips (1-page summary per date)
python3 -m app.cli batch --start 01/07/2023 --end 31/07/2023 --report-type payment-slip

# Batch options:
python3 -m app.cli batch --start 01/07/2023 --end 31/07/2023 --skip-sundays --delay 2.0
```

---

### 3. Single-Date Proof of Concept (`test-date`)

Verify credentials and test a single date:

```bash
# Test Bank Statement for a single date:
python3 -m app.cli test-date --date 10/10/2026

# Test Deposit Slip for a single date:
python3 -m app.cli test-date --date 01/07/2023 --report-type deposit-slip

# Test Payment Slip for a single date:
python3 -m app.cli test-date --date 01/07/2023 --report-type payment-slip
```

---

### 4. Merge Statements with Blank Separator (`merge`)

Merge existing PDF reports of a specific type in chronological order:

```bash
# Merge all Deposit Slips:
python3 -m app.cli merge --prefix DepositSlip --output-file Merged_DepositSlips.pdf

# Merge all Payment Slips:
python3 -m app.cli merge --prefix PaymentSlip --output-file Merged_PaymentSlips.pdf

# Merge all Bank Statements:
python3 -m app.cli merge --prefix BankStatement --output-file Merged_BankStatements.pdf
```

---

### 5. Date Schedule Preview (`generate-dates`)

Preview the scheduled dates without making HTTP calls:

```bash
python3 -m app.cli generate-dates --start 01/07/2023 --end 31/07/2023 --skip-sundays
```

---

## Windows 7 / 10 / 11 PowerShell Engine

Flash Automator includes a standalone PowerShell engine located in `powershell/` designed for Windows 7 SP1+ (PowerShell 2.0 / 3.0 / 5.1):

```powershell
# In PowerShell:
cd powershell

# 1. Single-Date Test:
.\FlashAutomator.ps1 -Mode TestDate -Date "01/07/2023"
.\FlashAutomator.ps1 -Mode TestDate -ReportType DepositSlip -Date "01/07/2023"

# 2. Batch Download:
.\FlashAutomator.ps1 -Mode Batch -ReportType DepositSlip -StartDate "01/07/2023" -EndDate "31/07/2023"

# 3. Cashbook Compilation:
.\FlashAutomator.ps1 -Mode Cashbook -Period "07/2023"
```

---

## Testing

```bash
# Run all Python unit tests (65 tests)
pytest

# Run PowerShell test suite (36 tests)
pwsh powershell/tests/Test-FlashAutomator.ps1
```

---

## License

Private repository for internal municipal operations.
