<#
.SYNOPSIS
    Flash Automator - KDMC MyNet Bank Account Statement (BAS) Automation for Windows 7 / 10 / 11.

.DESCRIPTION
    Automates daily Bank Account Statements in KDMC MyNet using direct authenticated
    HTTP requests instead of mouse-coordinate automation. Designed specifically to run
    reliably on Windows 7 SP1 (PowerShell 2.0 / 3.0 / 5.1) without external Python runtimes.

.EXAMPLE
    # Single-date proof of concept:
    .\FlashAutomator.ps1 -Mode TestDate -Date "10/10/2026"

.EXAMPLE
    # Full month batch with 1.5s rate-limiting delay:
    .\FlashAutomator.ps1 -Mode Batch -StartDate "01/10/2026" -EndDate "31/10/2026" -DelaySeconds 1.5

.EXAMPLE
    # Batch skipping Sundays:
    .\FlashAutomator.ps1 -Mode Batch -StartDate "01/10/2026" -EndDate "31/10/2026" -SkipSundays

.EXAMPLE
    # Preview date iteration without sending requests:
    .\FlashAutomator.ps1 -Mode GenerateDates -StartDate "01/10/2026" -EndDate "31/10/2026" -SkipSundays
#>

[CmdletBinding()]
param (
    [ValidateSet("TestDate", "Batch", "GenerateDates", "Merge", "Cashbook", "Help")]
    [string]$Mode = "Help",

    [ValidateSet("BAS", "DepositSlip", "PaymentSlip")]
    [string]$ReportType = "BAS",

    [Parameter(ValueFromPipelineByPropertyName = $true)]
    [string]$Date = "",

    [string]$StartDate = "",
    [string]$EndDate = "",

    [string]$Period = "",
    [string]$Month = "",
    [string]$Year = "",

    [string]$SessionCookie = "",
    [string]$CsrfToken = "",
    [string]$BaseUrl = "https://kdmc.gov.in/MainetService",
    [int]$FieldId = 4,
    [int]$AccountHeadId = 0,

    [string]$OutputDir = "./output",
    [string]$DebugDir = "./debug",
    [string]$OutputFile = "Merged_BankStatements.pdf",
    [switch]$NoBlankPage,
    [switch]$SaveHtml,
    [switch]$AllPages,

    [double]$DelaySeconds = 1.5,
    [switch]$WeekdaysOnly,
    [switch]$SkipSundays,
    [switch]$SkipSaturdays,
    [string[]]$ExcludeDates = @(),

    [switch]$NoResume,
    [switch]$Overwrite,
    [switch]$SkipCertificateCheck,
    [switch]$VerboseOutput,
    [string]$EnvFile = ".env"
)

Set-StrictMode -Off

# Dot-source core functions
$corePath = Join-Path $PSScriptRoot "FlashAutomatorCore.ps1"
if (-not (Test-Path $corePath)) {
    Write-Error "Cannot locate FlashAutomatorCore.ps1 at $corePath"
    exit 1
}
. $corePath

# ==============================================================================
# WORKFLOW EXECUTION RUNNER
# ==============================================================================

function Execute-SingleDateWorkflow {
    param (
        [string]$TargetDateStr
    )

    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    $parsedDate = [DateTime]::ParseExact($TargetDateStr, "dd/MM/yyyy", $culture)
    $cleanDate = $parsedDate.ToString("dd-MM-yyyy")

    $outDirPath = [System.IO.Path]::GetFullPath($OutputDir)
    if (-not (Test-Path $outDirPath)) {
        New-Item -ItemType Directory -Path $outDirPath -Force | Out-Null
    }

    $prefix = if ($ReportType -eq "DepositSlip") {
        "DepositSlip"
    } elseif ($ReportType -eq "PaymentSlip") {
        "PaymentSlip"
    } else {
        "BankStatement"
    }
    $htmlTarget = Join-Path $outDirPath "$($prefix)_$cleanDate.html"
    $pdfTarget = Join-Path $outDirPath "$($prefix)_$cleanDate.pdf"

    # Check resume state
    if ((-not $NoResume) -and (-not $Overwrite)) {
        if (Test-Path $pdfTarget) {
            $pdfItem = Get-Item $pdfTarget
            if ($pdfItem.Length -gt 1024) {
                Log-Info "[$TargetDateStr] Already completed: $($pdfItem.Name) (Skipping)."
                $resObj = New-Object PSObject
                $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
                $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "SKIPPED"
                $resObj | Add-Member -MemberType NoteProperty -Name "File" -Value $pdfTarget
                $resObj | Add-Member -MemberType NoteProperty -Name "Records" -Value 0
                return $resObj
            }
        }
    }

    # Deposit Slip Workflow (Direct BIRT vector PDF)
    if ($ReportType -eq "DepositSlip") {
        try {
            $bytesDownloaded = Download-DepositSlipPdf -TargetDateStr $TargetDateStr -DestinationPath $pdfTarget -SessionCookie $script:SessionCookie -LastPageOnly:(-not $AllPages)
            Log-Success "[$TargetDateStr] Generated Deposit Slip PDF: $([System.IO.Path]::GetFileName($pdfTarget)) ($bytesDownloaded bytes)"
            $resObj = New-Object PSObject
            $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
            $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "SUCCESS"
            $resObj | Add-Member -MemberType NoteProperty -Name "File" -Value $pdfTarget
            $resObj | Add-Member -MemberType NoteProperty -Name "Records" -Value 1
            return $resObj
        } catch {
            Log-ErrorMsg "[$TargetDateStr] Deposit Slip download failed: $_"
            $resObj = New-Object PSObject
            $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
            $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "ERROR"
            $resObj | Add-Member -MemberType NoteProperty -Name "Error" -Value "$_"
            return $resObj
        }
    }

    # Payment Slip Workflow (Direct BIRT vector PDF)
    if ($ReportType -eq "PaymentSlip") {
        try {
            $bytesDownloaded = Download-PaymentSlipPdf -TargetDateStr $TargetDateStr -DestinationPath $pdfTarget -SessionCookie $script:SessionCookie -LastPageOnly:(-not $AllPages)
            Log-Success "[$TargetDateStr] Generated Payment Slip PDF: $([System.IO.Path]::GetFileName($pdfTarget)) ($bytesDownloaded bytes)"
            $resObj = New-Object PSObject
            $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
            $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "SUCCESS"
            $resObj | Add-Member -MemberType NoteProperty -Name "File" -Value $pdfTarget
            $resObj | Add-Member -MemberType NoteProperty -Name "Records" -Value 1
            return $resObj
        } catch {
            Log-ErrorMsg "[$TargetDateStr] Payment Slip download failed: $_"
            $resObj = New-Object PSObject
            $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
            $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "ERROR"
            $resObj | Add-Member -MemberType NoteProperty -Name "Error" -Value "$_"
            return $resObj
        }
    }

    # Bank Account Statement Workflow (HTML form POST -> receipt -> PDF)
    # Ensure CSRF token
    if (-not $script:CsrfToken) {
        $script:CsrfToken = Refresh-CsrfToken -BaseUrl $BaseUrl -SessionCookie $script:SessionCookie -CurrentToken $script:CsrfToken
    }

    # Construct POST payload verified from HAR
    $escapedDate = [System.Uri]::EscapeDataString($TargetDateStr)
    $payload = "reportTypeCode=BAS&transactionDate=&fromDate=$escapedDate&toDate=$escapedDate&accountHeadId=$AccountHeadId&financialId=&transactionTypeCode=&registerDepTypeId=&categoryId=&paymodeId=&vendorId=&fieldId=$FieldId"
    $reportUrl = "$BaseUrl/AccountFinancialReport.html?report"
    $dailyRef = "$BaseUrl/AccountDailyReports.html"

    Log-Info "[$TargetDateStr] Submitting POST report request to KDMC portal..."
    $httpRes = Send-HttpRequest -Url $reportUrl -Method "POST" -PostData $payload -Referer $dailyRef -Csrf $script:CsrfToken -SessionCookie $script:SessionCookie

    # Save debug HTML if enabled
    if ($SaveHtml) {
        $dbgDir = [System.IO.Path]::GetFullPath($DebugDir)
        if (-not (Test-Path $dbgDir)) { New-Item -ItemType Directory -Path $dbgDir -Force | Out-Null }
        $rawFile = Join-Path $dbgDir "RawResponse_$cleanDate.html"
        [System.IO.File]::WriteAllText($rawFile, $httpRes.Body, [System.Text.Encoding]::UTF8)
        Log-Info "[$TargetDateStr] Saved raw server HTML: $rawFile"
    }

    # Validate response
    $val = Parse-ReportResponse -Html $httpRes.Body
    if (-not $val.IsValid) {
        Log-ErrorMsg "[$TargetDateStr] Validation failed: $($val.ErrorMessage)"
        $resObj = New-Object PSObject
        $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
        $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "ERROR"
        $resObj | Add-Member -MemberType NoteProperty -Name "Error" -Value $val.ErrorMessage
        return $resObj
    }

    if ($val.IsEmpty) {
        Log-Info "[$TargetDateStr] No financial statement records exist on portal for this date."
        $resObj = New-Object PSObject
        $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
        $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "NO_RECORDS"
        $resObj | Add-Member -MemberType NoteProperty -Name "Records" -Value 0
        return $resObj
    }

    # Save standalone print-ready HTML
    $printableDoc = Build-StandaloneHtmlDocument -ReceiptHtml $val.CleanHtml -Title "Bank Account Wise Balance Statement ($TargetDateStr)"
    [System.IO.File]::WriteAllText($htmlTarget, $printableDoc, [System.Text.Encoding]::UTF8)

    # Attempt PDF conversion (if Chromium / Edge / wkhtmltopdf is installed)
    $generatedPdf = Convert-HtmlToPdf -HtmlPath $htmlTarget -PdfPath $pdfTarget
    $finalFile = $htmlTarget
    if ($generatedPdf) {
        $finalFile = $generatedPdf
        Log-Success "[$TargetDateStr] Generated PDF: $([System.IO.Path]::GetFileName($finalFile)) ($($val.RecordCount) records)"
    } else {
        Log-Success "[$TargetDateStr] Saved printable statement: $([System.IO.Path]::GetFileName($htmlTarget)) ($($val.RecordCount) records)"
        Log-Info "Tip: Open $htmlTarget in your browser and press Ctrl+P to save/print as PDF."
    }

    $resObj = New-Object PSObject
    $resObj | Add-Member -MemberType NoteProperty -Name "Date" -Value $TargetDateStr
    $resObj | Add-Member -MemberType NoteProperty -Name "Status" -Value "SUCCESS"
    $resObj | Add-Member -MemberType NoteProperty -Name "File" -Value $finalFile
    $resObj | Add-Member -MemberType NoteProperty -Name "Records" -Value $val.RecordCount
    return $resObj
}

# ==============================================================================
# MAIN CONTROLLER
# ==============================================================================

Initialize-NetworkSecurity -SkipCertCheck:$SkipCertificateCheck

$script:SessionCookie = $SessionCookie
$script:CsrfToken = $CsrfToken

$scRef = [ref]$script:SessionCookie
$ctRef = [ref]$script:CsrfToken
Load-EnvConfig -Path $EnvFile -SessionCookieRef $scRef -CsrfTokenRef $ctRef

switch ($Mode) {
    "TestDate" {
        if (-not $Date) {
            Log-ErrorMsg "Missing -Date parameter. Example: .\FlashAutomator.ps1 -Mode TestDate -Date '10/10/2026'"
            exit 1
        }
        Log-Info "=========================================================="
        Log-Info "  FLASH AUTOMATOR: SINGLE-DATE TEST ($Date)"
        Log-Info "=========================================================="

        if (-not $script:SessionCookie) {
            Log-Warn "No session cookie found! Set KDMC_SESSION_COOKIE in .env or pass -SessionCookie."
        }

        $res = Execute-SingleDateWorkflow -TargetDateStr $Date
        if ($res.Status -eq "SUCCESS" -or $res.Status -eq "SKIPPED") {
            Log-Success "Single-date test finished successfully (Status: $($res.Status))!"
            exit 0
        } else {
            Log-ErrorMsg "Single-date test ended with status: $($res.Status)"
            exit 1
        }
    }

    "Batch" {
        if (-not $StartDate -or -not $EndDate) {
            Log-ErrorMsg "Missing -StartDate or -EndDate. Example: .\FlashAutomator.ps1 -Mode Batch -StartDate '01/10/2026' -EndDate '31/10/2026'"
            exit 1
        }
        Log-Info "=========================================================="
        Log-Info "  FLASH AUTOMATOR: BATCH STATEMENT AUTOMATION"
        Log-Info "  Range: $StartDate to $EndDate | Delay: $($DelaySeconds)s"
        Log-Info "=========================================================="

        if (-not $script:SessionCookie) {
            Log-Warn "No session cookie found! Set KDMC_SESSION_COOKIE in .env or pass -SessionCookie."
        }

        $sequence = Get-DateSequence -StartDateStr $StartDate -EndDateStr $EndDate -WeekdaysOnly:$WeekdaysOnly -SkipSundays:$SkipSundays -SkipSaturdays:$SkipSaturdays -ExcludeDates $ExcludeDates
        $included = $sequence | Where-Object { $_.IsIncluded }
        $total = @($included).Count

        Log-Info "Total Target Dates: $total (Total Evaluated: $(@($sequence).Count))"
        $results = @()
        $idx = 1

        foreach ($item in $included) {
            Log-Info "[$idx/$total] Processing date: $($item.DateStr) ($($item.DayOfWeek))..."
            $r = Execute-SingleDateWorkflow -TargetDateStr $item.DateStr
            $results += $r

            # Halt immediately on authentication failure
            if ($r.Status -eq "ERROR" -and $r.Error -match "Authentication expired") {
                Log-ErrorMsg "Session expired during batch. Halting execution."
                break
            }

            if ($idx -lt $total) {
                Start-Sleep -Seconds $DelaySeconds
            }
            $idx++
        }

        # Save manifest
        $manifestPath = Join-Path $OutputDir "execution_manifest.csv"
        $results | Export-Csv -Path $manifestPath -NoTypeInformation
        Log-Info "Execution audit manifest saved to: $manifestPath"

        $successCount = @($results | Where-Object { $_.Status -eq "SUCCESS" }).Count
        $skippedCount = @($results | Where-Object { $_.Status -eq "SKIPPED" }).Count
        $noRecCount = @($results | Where-Object { $_.Status -eq "NO_RECORDS" }).Count
        $errCount = @($results | Where-Object { $_.Status -eq "ERROR" }).Count

        Log-Info "----------------------------------------------------------"
        Log-Info "BATCH SUMMARY: Success: $successCount | Skipped: $skippedCount | No Records: $noRecCount | Errors: $errCount"
        Log-Info "----------------------------------------------------------"

        if ($errCount -gt 0) { exit 1 } else { exit 0 }
    }

    "GenerateDates" {
        if (-not $StartDate -or -not $EndDate) {
            Log-ErrorMsg "Missing -StartDate or -EndDate. Example: .\FlashAutomator.ps1 -Mode GenerateDates -StartDate '01/10/2026' -EndDate '31/10/2026'"
            exit 1
        }
        $sequence = Get-DateSequence -StartDateStr $StartDate -EndDateStr $EndDate -WeekdaysOnly:$WeekdaysOnly -SkipSundays:$SkipSundays -SkipSaturdays:$SkipSaturdays -ExcludeDates $ExcludeDates
        Write-Host "`nDate Iteration Schedule ($StartDate to $EndDate):" -ForegroundColor White
        Write-Host ("{0,-4} {1,-12} {2,-11} {3,-10} {4}" -f "#", "Date", "Day", "Status", "Reason") -ForegroundColor DarkGray
        Write-Host ("-" * 65) -ForegroundColor DarkGray

        $count = 1
        foreach ($s in $sequence) {
            $status = if ($s.IsIncluded) { "INCLUDED" } else { "SKIPPED" }
            $reason = if ($s.SkipReason) { $s.SkipReason } else { "" }
            $color = if ($s.IsIncluded) { "Green" } else { "DarkYellow" }
            Write-Host ("{0,-4} {1,-12} {2,-11} {3,-10} {4}" -f $count, $s.DateStr, $s.DayOfWeek, $status, $reason) -ForegroundColor $color
            $count++
        }
        $incCount = @($sequence | Where-Object { $_.IsIncluded }).Count
        Write-Host ("-" * 65) -ForegroundColor DarkGray
        Write-Host "Total: $(@($sequence).Count) | Included: $incCount | Skipped: $(@($sequence).Count - $incCount)`n" -ForegroundColor White
        exit 0
    }

    "Merge" {
        Log-Info "--- Running PDF Statement Merge Workflow ---"
        $pyCmd = $null
        if (Get-Command "python3" -ErrorAction SilentlyContinue) {
            $pyCmd = "python3"
        } elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
            $pyCmd = "python"
        }

        if ($pyCmd) {
            $mergeArgs = @("-m", "app.cli", "merge", "--input-dir", $OutputDir)
            if ($ReportType -eq "DepositSlip") {
                $mergeArgs += @("--prefix", "DepositSlip")
                if (-not $OutputFile -or $OutputFile -eq "Merged_BankStatements.pdf") {
                    $OutputFile = "Merged_DepositSlips.pdf"
                }
            } elseif ($ReportType -eq "PaymentSlip") {
                $mergeArgs += @("--prefix", "PaymentSlip")
                if (-not $OutputFile -or $OutputFile -eq "Merged_BankStatements.pdf") {
                    $OutputFile = "Merged_PaymentSlips.pdf"
                }
            }
            if ($OutputFile) {
                $mergeArgs += @("--output-file", $OutputFile)
            }
            if ($NoBlankPage) {
                $mergeArgs += "--no-blank-page"
            }
            Log-Info "Delegating PDF merge to $pyCmd with blank separator page insertion..."
            & $pyCmd $mergeArgs
            exit $LASTEXITCODE
        } else {
            Log-ErrorMsg "Python runtime with 'pypdf' installed is required for PDF manipulation. Run: python -m app.cli merge"
            exit 1
        }
    }

    "Cashbook" {
        Log-Info "--- Running Final Cashbook Assembly Workflow ---"
        $pyCmd = $null
        if (Get-Command "python3" -ErrorAction SilentlyContinue) {
            $pyCmd = "python3"
        } elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
            $pyCmd = "python"
        }

        if ($pyCmd) {
            $cashArgs = @("-m", "app.cli", "cashbook", "--input-dir", $OutputDir)
            if ($Period) {
                $cashArgs += @("--period", $Period)
            }
            if ($Month) {
                $cashArgs += @("--month", $Month)
            }
            if ($Year) {
                $cashArgs += @("--year", $Year)
            }
            if ($OutputFile -and $OutputFile -ne "Merged_BankStatements.pdf") {
                $cashArgs += @("--output-file", $OutputFile)
            }
            if ($NoBlankPage) {
                $cashArgs += "--no-blank-page"
            }
            if ($Overwrite) {
                $cashArgs += "--overwrite"
            }
            if ($DelaySeconds) {
                $cashArgs += @("--delay", $DelaySeconds)
            }
            if ($WeekdaysOnly) {
                $cashArgs += "--weekdays-only"
            }
            if ($SkipSundays) {
                $cashArgs += "--skip-sundays"
            }
            if ($SkipSaturdays) {
                $cashArgs += "--skip-saturdays"
            }
            if ($ExcludeDates -and $ExcludeDates.Count -gt 0) {
                $cashArgs += @("--exclude-dates", ($ExcludeDates -join ","))
            }
            Log-Info "Delegating Final Cashbook compilation to $pyCmd with blank separator page insertion..."
            & $pyCmd $cashArgs
            exit $LASTEXITCODE
        } else {
            Log-ErrorMsg "Python runtime with 'pypdf' installed is required for PDF manipulation. Run: python -m app.cli cashbook"
            exit 1
        }
    }

    Default {
        Write-Host @"
Flash Automator (PowerShell Engine for Windows 7 / 10 / 11)
------------------------------------------------------------
Commands:
  1. Single-Date Proof of Concept:
     .\FlashAutomator.ps1 -Mode TestDate -Date "10/10/2026"
     .\FlashAutomator.ps1 -Mode TestDate -ReportType DepositSlip -Date "01/07/2023"
     .\FlashAutomator.ps1 -Mode TestDate -ReportType PaymentSlip -Date "01/07/2023"

  2. Sequential Month Batch Automation:
     .\FlashAutomator.ps1 -Mode Batch -StartDate "01/10/2026" -EndDate "31/10/2026"
     .\FlashAutomator.ps1 -Mode Batch -ReportType DepositSlip -StartDate "01/07/2023" -EndDate "31/07/2023"
     .\FlashAutomator.ps1 -Mode Batch -ReportType PaymentSlip -StartDate "01/07/2023" -EndDate "31/07/2023"

  3. Batch Skipping Sundays:
     .\FlashAutomator.ps1 -Mode Batch -StartDate "01/10/2026" -EndDate "31/10/2026" -SkipSundays

  4. Date Preview without Network Traffic:
     .\FlashAutomator.ps1 -Mode GenerateDates -StartDate "01/10/2026" -EndDate "31/10/2026" -SkipSundays

  5. Merge Generated PDFs with 1 Blank Page Separator:
     .\FlashAutomator.ps1 -Mode Merge
     .\FlashAutomator.ps1 -Mode Merge -ReportType DepositSlip
     .\FlashAutomator.ps1 -Mode Merge -ReportType PaymentSlip

  6. Assemble Final Cashbook (Bank Report -> Deposit -> Payment with 1 Blank Page):
     .\FlashAutomator.ps1 -Mode Cashbook -Period "07/2023"
     .\FlashAutomator.ps1 -Mode Cashbook -Month 7 -Year 2023

Parameters:
  -ReportType <BAS|DepositSlip|PaymentSlip> Type of report to generate (default: BAS)
  -Period <MM/YYYY>             Month and year for Cashbook (e.g. 07/2023)
  -AllPages                     Download all pages instead of only the last summary page for slips
  -DelaySeconds <float>         Pause between requests in seconds (default: 1.5)
  -OutputDir <path>             Destination folder for statements (default: ./output)
  -OutputFile <string>          Filename for merged PDF
  -NoBlankPage                  Disable insertion of blank separator pages
  -SaveHtml                     Save raw server HTML for debugging (BAS only)
  -Overwrite                    Re-download statements even if file exists
  -SkipCertificateCheck         Bypass SSL certificate checks on legacy Windows 7
"@ -ForegroundColor Yellow
        exit 0
    }
}
