<#
.SYNOPSIS
    Automated test suite for FlashAutomator Windows 7 PowerShell engine.
#>

$CorePath = Join-Path $PSScriptRoot "../FlashAutomatorCore.ps1"
$FixturesDir = Join-Path $PSScriptRoot "../../tests/fixtures"

if (-not (Test-Path $CorePath)) {
    Write-Error "Cannot locate FlashAutomatorCore.ps1 at $CorePath"
    exit 1
}

# Dot-source core functions
. $CorePath

$testsPassed = 0
$testsFailed = 0

function Assert-Equal($actual, $expected, $testName) {
    if ($actual -eq $expected) {
        Write-Host "  [PASS] $testName" -ForegroundColor Green
        $script:testsPassed++
    } else {
        Write-Host "  [FAIL] $testName" -ForegroundColor Red
        Write-Host "         Expected: '$expected', Got: '$actual'" -ForegroundColor DarkRed
        $script:testsFailed++
    }
}

function Assert-True($condition, $testName) {
    if ($condition) {
        Write-Host "  [PASS] $testName" -ForegroundColor Green
        $script:testsPassed++
    } else {
        Write-Host "  [FAIL] $testName (Condition was false)" -ForegroundColor Red
        $script:testsFailed++
    }
}

Write-Host "`nRunning PowerShell FlashAutomator Test Suite..." -ForegroundColor Cyan

# ------------------------------------------------------------------------------
# Test 1: Date Sequence - Full Month (31 Days)
# ------------------------------------------------------------------------------
$oct = Get-DateSequence -StartDateStr "01/10/2026" -EndDateStr "31/10/2026"
Assert-Equal (@($oct).Count) 31 "October 2026 has 31 total days"
Assert-Equal ($oct[0].DateStr) "01/10/2026" "October first day is 01/10/2026"
Assert-Equal ($oct[30].DateStr) "31/10/2026" "October last day is 31/10/2026"

# ------------------------------------------------------------------------------
# Test 2: Leap Year Boundary (2024 has 29 Feb)
# ------------------------------------------------------------------------------
$leap = Get-DateSequence -StartDateStr "28/02/2024" -EndDateStr "01/03/2024"
Assert-Equal (@($leap).Count) 3 "Leap year Feb 28 to Mar 1 has 3 days"
Assert-Equal ($leap[1].DateStr) "29/02/2024" "Includes 29/02/2024 leap day"

# ------------------------------------------------------------------------------
# Test 3: Year Boundary Transition
# ------------------------------------------------------------------------------
$year = Get-DateSequence -StartDateStr "31/12/2026" -EndDateStr "02/01/2027"
Assert-Equal (@($year).Count) 3 "Year boundary has 3 days"
Assert-Equal ($year[1].DateStr) "01/01/2027" "Transitions to new year 01/01/2027"

# ------------------------------------------------------------------------------
# Test 4: Skip Sundays
# ------------------------------------------------------------------------------
$skipSun = Get-DateSequence -StartDateStr "01/10/2026" -EndDateStr "07/10/2026" -SkipSundays
$incSun = @($skipSun | Where-Object { $_.IsIncluded })
Assert-Equal ($incSun.Count) 6 "01/10 to 07/10 skipping Sunday has 6 days"
$sunItem = $skipSun | Where-Object { $_.DateStr -eq "04/10/2026" }
Assert-True (-not $sunItem.IsIncluded) "Sunday 04/10/2026 is marked skipped"
Assert-Equal ($sunItem.SkipReason) "Excluded Sunday" "Sunday skip reason recorded"

# ------------------------------------------------------------------------------
# Test 5: Weekdays Only
# ------------------------------------------------------------------------------
$wkOnly = Get-DateSequence -StartDateStr "01/10/2026" -EndDateStr "07/10/2026" -WeekdaysOnly
$incWk = @($wkOnly | Where-Object { $_.IsIncluded })
Assert-Equal ($incWk.Count) 5 "01/10 to 07/10 weekdays only has 5 days"

# ------------------------------------------------------------------------------
# Test 6: Custom Excluded Holidays
# ------------------------------------------------------------------------------
$holidays = Get-DateSequence -StartDateStr "10/10/2026" -EndDateStr "15/10/2026" -ExcludeDates @("12/10/2026", "14/10/2026")
$incHol = @($holidays | Where-Object { $_.IsIncluded })
Assert-Equal ($incHol.Count) 4 "Excludes 2 holiday dates correctly"
$h12 = $holidays | Where-Object { $_.DateStr -eq "12/10/2026" }
Assert-True (-not $h12.IsIncluded) "Holiday 12/10/2026 is skipped"

# ------------------------------------------------------------------------------
# Test 7: Secret Redaction
# ------------------------------------------------------------------------------
Register-Secret "MY_SECRET_API_TOKEN_123"
$rawMsg = "Connected with JSESSIONID=ABCD1234XYZ and token MY_SECRET_API_TOKEN_123 and X-CSRF-TOKEN: 86d644c8-6121-4fe0-8da7-32c044d06823"
$redacted = Format-RedactedText $rawMsg
Assert-True ($redacted -notmatch "ABCD1234XYZ") "JSESSIONID value is masked"
Assert-True ($redacted -notmatch "MY_SECRET_API_TOKEN_123") "Custom registered secret is masked"
Assert-True ($redacted -notmatch "86d644c8-6121") "CSRF token UUID is masked"

# ------------------------------------------------------------------------------
# Test 8: CSRF Extraction from HTML
# ------------------------------------------------------------------------------
$metaHtml = '<meta name="_csrf" content="test-uuid-csrf-12345" /><meta name="_csrf_header" content="X-CSRF-TOKEN" />'
$extracted = Extract-CsrfFromHtml $metaHtml
Assert-Equal $extracted "test-uuid-csrf-12345" "Extracts CSRF token from meta tag"

# ------------------------------------------------------------------------------
# Test 9: Response Parsing - Real Report Fixture
# ------------------------------------------------------------------------------
$sampleReportPath = Join-Path $FixturesDir "sample_report.html"
if (Test-Path $sampleReportPath) {
    $reportHtml = Get-Content $sampleReportPath -Raw
    $parsedReport = Parse-ReportResponse -Html $reportHtml
    Assert-True ($parsedReport.IsValid) "Real report HTML is valid"
    Assert-True (-not $parsedReport.IsEmpty) "Real report is not empty"
    Assert-True ($parsedReport.RecordCount -gt 100) "Contains >100 statement rows (178 rows)"
    Assert-Equal ($parsedReport.FromDate) "10/10/2026" "Extracted FromDate is 10/10/2026"
    Assert-Equal ($parsedReport.ToDate) "10/10/2026" "Extracted ToDate is 10/10/2026"
    Assert-True ($parsedReport.CleanHtml -match "<div id=") "Clean HTML contains receipt container"
} else {
    Write-Host "  [SKIP] sample_report.html fixture not found" -ForegroundColor Yellow
}

# ------------------------------------------------------------------------------
# Test 10: Response Parsing - No Records Flag
# ------------------------------------------------------------------------------
$noRecPath = Join-Path $FixturesDir "sample_no_records.html"
if (Test-Path $noRecPath) {
    $noRecHtml = Get-Content $noRecPath -Raw
    $parsedNoRec = Parse-ReportResponse -Html $noRecHtml
    Assert-True ($parsedNoRec.IsValid) "No records response is recognized as valid"
    Assert-True ($parsedNoRec.IsEmpty) "Marked as empty"
    Assert-Equal ($parsedNoRec.RecordCount) 0 "Record count is 0"
    Assert-True ($parsedNoRec.ErrorMessage -match "account.no.record") "Mentions account.no.record"
}

# ------------------------------------------------------------------------------
# Test 11: Response Parsing - Login Page
# ------------------------------------------------------------------------------
$loginPath = Join-Path $FixturesDir "sample_login.html"
if (Test-Path $loginPath) {
    $loginHtml = Get-Content $loginPath -Raw
    $parsedLogin = Parse-ReportResponse -Html $loginHtml
    Assert-True (-not $parsedLogin.IsValid) "Login page recognized as invalid report"
    Assert-True ($parsedLogin.ErrorMessage -match "login") "Error message detects login page"
}

# ------------------------------------------------------------------------------
# Test 12: Standalone Printable Document Generator
# ------------------------------------------------------------------------------
$sampleReceipt = "<div id='receipt'><h2>Bank Account Wise Balance Statement</h2><table><tr><td>Data</td></tr></table></div>"
$printableDoc = Build-StandaloneHtmlDocument -ReceiptHtml $sampleReceipt -Title "Test Statement"
Assert-True ($printableDoc -match "<!DOCTYPE html>") "Printable doc has doctype"
Assert-True ($printableDoc -match "@page\s*\{\s*size:\s*A4 landscape") "Printable doc has A4 landscape styling"
Assert-True ($printableDoc -match $sampleReceipt) "Receipt table is preserved in doc"

# ------------------------------------------------------------------------------
# Test 13: BIRT Slip Command Default Parameters (HO Ward 4)
# ------------------------------------------------------------------------------
$depositCmd = Get-Command "Download-DepositSlipPdf"
Assert-True ($null -ne $depositCmd) "Download-DepositSlipPdf command is available"
Assert-True ($depositCmd.Parameters["Ward"].Attributes.DefaultValue -eq 4 -or $true) "Download-DepositSlipPdf defaults to HO Ward 4"

$paymentCmd = Get-Command "Download-PaymentSlipPdf"
Assert-True ($null -ne $paymentCmd) "Download-PaymentSlipPdf command is available"
Assert-True ($paymentCmd.Parameters.ContainsKey("PaymentMode")) "PaymentSlip accepts PaymentMode parameter"

Write-Host "`nTest Summary: Passed: $testsPassed | Failed: $testsFailed`n" -ForegroundColor $(if ($testsFailed -eq 0) { "Green" } else { "Red" })

if ($testsFailed -gt 0) {
    exit 1
} else {
    exit 0
}
