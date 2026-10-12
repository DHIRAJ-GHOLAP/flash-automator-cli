# Flash Automator: Native PowerShell Engine for Windows 7 / 10 / 11 ⚡

This folder contains a 100% native PowerShell implementation of the **KDMC MyNet Bank Account Statement (BAS) HTTP Automation** engine.

It is specifically engineered to run out-of-the-box on legacy **Windows 7 SP1** machines **without requiring Python, PySide6, or external pip packages**.

---

## 🌟 Why Native PowerShell for Windows 7?

- **Zero Runtime Dependencies:** Runs on built-in Windows 7 PowerShell (PowerShell 2.0, 3.0, 4.0, or 5.1) and .NET 3.5/4.0+.
- **Automatic TLS 1.2 Activation:** Overcomes Windows 7's default TLS 1.0 limitation by dynamically enabling TLS 1.2 (`[Net.SecurityProtocolType]3072`) so it can connect to modern municipal HTTPS portals.
- **Spring Security CSRF & Session Synchronization:** Matches the exact POST payload and AJAX headers verified from the portal HAR capture.
- **A4 Landscape Print Output:** Generates self-contained, clean HTML statement documents matching the frontend `PrintDiv('')` layout. If Chrome, Edge, Brave, or `wkhtmltopdf` is detected, it automatically converts them to PDF (`BankStatement_DD-MM-YYYY.pdf`).
- **Audit Compliance:** Writes `execution_manifest.csv` and redacts all cookies, tokens, and passwords from logs.

---

## 🚀 Quick Start on Windows 7

### Step 1: Configure Your Session Cookie
1. Log into **KDMC MyNet** in your browser.
2. Press `F12` -> Application / Storage -> Cookies -> `https://kdmc.gov.in`.
3. Copy the value of **`JSESSIONID`**.
4. Open or create `.env` in the project root:
   ```ini
   KDMC_SESSION_COOKIE=YOUR_JSESSIONID_COOKIE_VALUE
   ```

---

### Step 2: Run Commands

You can run commands using **`Run-FlashAutomator.bat`** (double-clickable or via Command Prompt) or directly via **PowerShell**:

#### 1. Single-Date Proof of Concept
Tests downloading a report for a single date (extracts only the 1-page daily summary for slips):
```cmd
:: Bank Account Statement (BAS) - HO Main Branch:
Run-FlashAutomator.bat -Mode TestDate -Date "10/10/2026"

:: Deposit Slip Report (1-page summary) - HO Main Branch:
Run-FlashAutomator.bat -Mode TestDate -ReportType DepositSlip -Date "01/07/2023"

:: Payment Slip Report (1-page summary) - HO Main Branch:
Run-FlashAutomator.bat -Mode TestDate -ReportType PaymentSlip -Date "01/07/2023"
```

#### 2. Sequential Month Batch Processing
Loops through every day of the month sequentially with polite 1.5s pauses:
```cmd
:: Bank Account Statements:
Run-FlashAutomator.bat -Mode Batch -StartDate "01/07/2023" -EndDate "31/07/2023" -DelaySeconds 1.5

:: Deposit Slips (1-page summary per day):
Run-FlashAutomator.bat -Mode Batch -ReportType DepositSlip -StartDate "01/07/2023" -EndDate "31/07/2023" -DelaySeconds 1.5

:: Payment Slips (1-page summary per day):
Run-FlashAutomator.bat -Mode Batch -ReportType PaymentSlip -StartDate "01/07/2023" -EndDate "31/07/2023" -DelaySeconds 1.5
```
*Advanced options:*
- **All Pages (Slips):** `-AllPages` (download full multi-page receipts instead of only the 1-page summary)
- **Skip Sundays:** `-SkipSundays`
- **Weekdays Only (Mon-Fri):** `-WeekdaysOnly`
- **Exclude Holidays:** `-ExcludeDates "15/10/2026","24/10/2026"`
- **Skip Certificate Verification (for legacy Windows 7 root stores):** `-SkipCertificateCheck`

#### 3. Date Schedule Preview
Previews the date range and verified skip reasons without sending network requests:
```cmd
Run-FlashAutomator.bat -Mode GenerateDates -StartDate "01/10/2026" -EndDate "31/10/2026" -SkipSundays
```

#### 4. Merge All Daily PDFs (with 1 Blank Page Separator)
Merges all generated statements or slips chronologically into one PDF with 1 blank separator page between each daily report:
```cmd
:: Merge Bank Statements:
Run-FlashAutomator.bat -Mode Merge

:: Merge Deposit Slips:
Run-FlashAutomator.bat -Mode Merge -ReportType DepositSlip

:: Merge Payment Slips:
Run-FlashAutomator.bat -Mode Merge -ReportType PaymentSlip
```
*(Requires Python on the system for PDF processing).*

#### 5. Assemble Final Cashbook {Month/Year} (Duplex Print Ready)
Compiles the comprehensive municipal Cashbook for the month. For each day, it orders **Bank Report -> Deposit Slip -> Payment Slip**, inserting exactly **1 empty page between all documents**:
```cmd
:: Auto-detect month from downloaded files:
Run-FlashAutomator.bat -Mode Cashbook

:: Specify period (MM/YYYY):
Run-FlashAutomator.bat -Mode Cashbook -Period "07/2023"

:: Or specify Month and Year:
Run-FlashAutomator.bat -Mode Cashbook -Month 7 -Year 2023
```
Output: `output/Final_Cashbook_July_2023.pdf` *(Ready for duplex printing and physical municipal audit binder)*.

---

## 📁 Output & Printing on Windows 7

All generated files are saved to the **`./output/`** directory:
- **`BankStatement_DD-MM-YYYY.pdf`** (if Chrome, Edge, Brave, or `wkhtmltopdf` is installed)
- **`BankStatement_DD-MM-YYYY.html`** (standalone, print-ready document formatted for A4 landscape)
- **`execution_manifest.csv`** (audit trail recording date, record count, execution status, and files)

> 💡 **Tip:** If your Windows 7 machine does not have a PDF converter installed, simply double-click the `.html` statement file to open it in your browser and press **`Ctrl + P`** to print or save as PDF!

---

## 🛠️ Windows 7 Troubleshooting

### 1. Execution Policy Restriction
If PowerShell reports: `File FlashAutomator.ps1 cannot be loaded because running scripts is disabled on this system`:
Run via `Run-FlashAutomator.bat` or run:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### 2. SSL/TLS Certificate Errors
If Windows 7 has not received Windows Updates since 2020, its root certificate store may not recognize modern intermediate authorities:
Add the **`-SkipCertificateCheck`** switch:
```powershell
.\FlashAutomator.ps1 -Mode Batch -StartDate "01/10/2026" -EndDate "31/10/2026" -SkipCertificateCheck
```

### 3. Session Expiration
If the municipal session expires, the script halts immediately with `Authentication expired`. Simply log back in via your browser and update `KDMC_SESSION_COOKIE` in `.env`.
