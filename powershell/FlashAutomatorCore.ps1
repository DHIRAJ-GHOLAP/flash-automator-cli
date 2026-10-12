<#
.SYNOPSIS
    Flash Automator - Core Engine Functions for Windows 7 / 10 / 11 PowerShell.
#>

# ==============================================================================
# 1. WINDOWS 7 TLS 1.2 & NETWORKING COMPATIBILITY
# ==============================================================================

function Initialize-NetworkSecurity {
    param([switch]$SkipCertCheck)
    # Windows 7 by default uses TLS 1.0 in .NET 3.5/4.0.
    # Enable TLS 1.2 (3072), TLS 1.1 (768), and TLS 1.0 (192).
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]3072 -bor [System.Net.SecurityProtocolType]768 -bor [System.Net.SecurityProtocolType]192
    } catch {
        try {
            [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls
        } catch {}
    }

    if ($SkipCertCheck) {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
}

# ==============================================================================
# 2. LOGGING & SECRET REDACTION
# ==============================================================================

$script:KnownSecrets = @()

function Register-Secret {
    param([string]$Secret)
    if ($Secret -and $Secret.Trim().Length -gt 4) {
        $script:KnownSecrets += $Secret.Trim()
    }
}

function Format-RedactedText {
    param([string]$Text)
    if (-not $Text) { return $Text }
    $res = [string]$Text
    $res = [regex]::Replace($res, '(?i)(JSESSIONID=)[^;\s&]+', '$1***REDACTED***')
    $res = [regex]::Replace($res, '(?i)(X-CSRF-TOKEN[:=]\s*)[0-9a-fA-F-]+', '$1***REDACTED***')
    $res = [regex]::Replace($res, '(?i)(_csrf[:=]\s*)[0-9a-fA-F-]+', '$1***REDACTED***')
    $res = [regex]::Replace($res, '(?i)(password=)[^&\s]+', '$1***REDACTED***')
    foreach ($s in $script:KnownSecrets) {
        if ($s -and $s.Length -gt 4) {
            $res = $res.Replace($s, '***REDACTED***')
        }
    }
    return $res
}

function Log-Info {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $clean = Format-RedactedText $Message
    Write-Host "[$ts] [INFO] $clean" -ForegroundColor Cyan
}

function Log-Success {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $clean = Format-RedactedText $Message
    Write-Host "[$ts] [SUCCESS] $clean" -ForegroundColor Green
}

function Log-Warn {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $clean = Format-RedactedText $Message
    Write-Host "[$ts] [WARN] $clean" -ForegroundColor Yellow
}

function Log-ErrorMsg {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $clean = Format-RedactedText $Message
    Write-Host "[$ts] [ERROR] $clean" -ForegroundColor Red
}

# ==============================================================================
# 3. ENVIRONMENT & CONFIGURATION
# ==============================================================================

function Load-EnvConfig {
    param(
        [string]$Path = ".env",
        [ref]$SessionCookieRef,
        [ref]$CsrfTokenRef
    )
    $candidates = @($Path, ".env", "../.env", (Join-Path $PSScriptRoot ".env"), (Join-Path $PSScriptRoot "../.env"))
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) {
            Log-Info "Loading settings from environment file: $c"
            Get-Content $c | ForEach-Object {
                $line = $_.Trim()
                if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                    $eq = $line.IndexOf("=")
                    $k = $line.Substring(0, $eq).Trim()
                    $v = $line.Substring($eq + 1).Trim()
                    if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
                        $v = $v.Substring(1, $v.Length - 2)
                    }
                    if (-not [System.Environment]::GetEnvironmentVariable($k)) {
                        [System.Environment]::SetEnvironmentVariable($k, $v)
                    }
                }
            }
            break
        }
    }

    if ($SessionCookieRef -and -not $SessionCookieRef.Value) {
        $sc = [System.Environment]::GetEnvironmentVariable("KDMC_SESSION_COOKIE")
        if (-not $sc) { $sc = [System.Environment]::GetEnvironmentVariable("JSESSIONID") }
        if ($sc -and $sc.StartsWith("JSESSIONID=")) { $sc = $sc.Substring("JSESSIONID=".Length) }
        if ($sc) {
            $SessionCookieRef.Value = $sc
            Register-Secret $sc
        }
    }

    if ($CsrfTokenRef -and -not $CsrfTokenRef.Value) {
        $ct = [System.Environment]::GetEnvironmentVariable("KDMC_CSRF_TOKEN")
        if ($ct) {
            $CsrfTokenRef.Value = $ct
            Register-Secret $ct
        }
    }
}

# ==============================================================================
# 4. HTTP CLIENT (PowerShell 2.0+ & .NET 2.0/3.5/4.x/Core)
# ==============================================================================

function Send-HttpRequest {
    param (
        [string]$Url,
        [string]$Method = "GET",
        [string]$PostData = "",
        [string]$Referer = "",
        [string]$Csrf = "",
        [string]$SessionCookie = "",
        [int]$TimeoutMs = 30000
    )

    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Method = $Method
    $request.Timeout = $TimeoutMs
    $request.ReadWriteTimeout = $TimeoutMs
    $request.AllowAutoRedirect = $false
    $request.UserAgent = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
    $request.Accept = "text/html, */*; q=0.01"

    $cookieJar = New-Object System.Net.CookieContainer
    if ($SessionCookie) {
        $request.Headers.Add("Cookie", "JSESSIONID=$SessionCookie")
        try {
            $uriObj = New-Object System.Uri($Url)
            $c = New-Object System.Net.Cookie("JSESSIONID", $SessionCookie, "/", $uriObj.Host)
            $cookieJar.Add($c)
        } catch {}
    }
    $request.CookieContainer = $cookieJar

    if ($Referer) {
        $request.Referer = $Referer
        $request.Headers.Add("Origin", "https://kdmc.gov.in")
    }
    $request.Headers.Add("X-Requested-With", "XMLHttpRequest")

    if ($Csrf) {
        $request.Headers.Add("X-CSRF-TOKEN", $Csrf)
    }

    if ($Method -eq "POST") {
        $request.ContentType = "application/x-www-form-urlencoded; charset=UTF-8"
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($PostData)
        $request.ContentLength = $bytes.Length
        $reqStream = $request.GetRequestStream()
        $reqStream.Write($bytes, 0, $bytes.Length)
        $reqStream.Close()
    }

    $response = $null
    try {
        $response = $request.GetResponse()
    } catch [System.Net.WebException] {
        $webEx = $_.Exception
        if ($webEx.Response) {
            $response = $webEx.Response
        } else {
            throw $webEx
        }
    }

    $statusCode = [int]$response.StatusCode
    $reader = New-Object System.IO.StreamReader($response.GetResponseStream(), [System.Text.Encoding]::UTF8)
    $body = $reader.ReadToEnd()
    $reader.Close()
    $response.Close()

    $outObj = New-Object PSObject
    $outObj | Add-Member -MemberType NoteProperty -Name "StatusCode" -Value $statusCode
    $outObj | Add-Member -MemberType NoteProperty -Name "Body" -Value $body
    return $outObj
}

function Extract-CsrfFromHtml {
    param([string]$Html)
    if (-not $Html) { return $null }
    if ($Html -match '(?i)<meta\s+[^>]*name=["'']_csrf["''][^>]*content=["'']([^"'']+)["'']') {
        return $matches[1]
    }
    if ($Html -match '(?i)<meta\s+[^>]*content=["'']([^"'']+)["''][^>]*name=["'']_csrf["'']') {
        return $matches[1]
    }
    if ($Html -match '(?i)<input\s+[^>]*name=["'']_csrf["''][^>]*value=["'']([^"'']+)["'']') {
        return $matches[1]
    }
    if ($Html -match '(?i)<input\s+[^>]*value=["'']([^"'']+)["''][^>]*name=["'']_csrf["'']') {
        return $matches[1]
    }
    return $null
}

function Refresh-CsrfToken {
    param (
        [string]$BaseUrl,
        [string]$SessionCookie,
        [string]$CurrentToken = ""
    )
    Log-Info "Acquiring / refreshing CSRF token from portal..."
    $dailyUrl = "$BaseUrl/AccountDailyReports.html"
    try {
        $res = Send-HttpRequest -Url $dailyUrl -Method "GET" -SessionCookie $SessionCookie
        $token = Extract-CsrfFromHtml $res.Body
        if ($token) {
            Register-Secret $token
            Log-Info "Successfully extracted CSRF token from Daily Reports page."
            return $token
        }
    } catch {
        Log-Warn "Could not reach Daily Reports page directly: $_"
    }

    try {
        $onTypeUrl = "$BaseUrl/AccountFinancialReport.html?onReportType"
        $res = Send-HttpRequest -Url $onTypeUrl -Method "POST" -PostData "reportTypeCode=BAS" -Referer $dailyUrl -Csrf $CurrentToken -SessionCookie $SessionCookie
        $token = Extract-CsrfFromHtml $res.Body
        if ($token) {
            Register-Secret $token
            Log-Info "Acquired CSRF token via onReportType form selection."
            return $token
        }
    } catch {
        Log-Warn "Could not fetch token via onReportType: $_"
    }
    return $CurrentToken
}

# ==============================================================================
# 5. RESPONSE VALIDATION & CLEAN HTML EXTRACTION
# ==============================================================================

function Parse-ReportResponse {
    param([string]$Html)

    $parsed = New-Object PSObject
    $parsed | Add-Member -MemberType NoteProperty -Name "IsValid" -Value $false
    $parsed | Add-Member -MemberType NoteProperty -Name "IsEmpty" -Value $false
    $parsed | Add-Member -MemberType NoteProperty -Name "RecordCount" -Value 0
    $parsed | Add-Member -MemberType NoteProperty -Name "FromDate" -Value $null
    $parsed | Add-Member -MemberType NoteProperty -Name "ToDate" -Value $null
    $parsed | Add-Member -MemberType NoteProperty -Name "ErrorMessage" -Value $null
    $parsed | Add-Member -MemberType NoteProperty -Name "CleanHtml" -Value $null

    if (-not $Html -or [string]::IsNullOrWhiteSpace($Html)) {
        $parsed.ErrorMessage = "Empty response received from server."
        return $parsed
    }

    # 1. Error flag check (#errorId == 'Y')
    if ($Html -match '(?i)id=["'']errorId["''][^>]*value=["'']Y["'']' -or $Html -match '(?i)value=["'']Y["''][^>]*id=["'']errorId["'']') {
        $parsed.IsValid = $true
        $parsed.IsEmpty = $true
        $parsed.ErrorMessage = "No records found for the requested date (KDMC account.no.record)."
        return $parsed
    }

    # 2. Login redirect / session expiration
    if ($Html -match '(?i)j_username' -or $Html -match '(?i)login\.html' -or $Html -match '(?i)session\s+expired' -or $Html -match '(?i)please\s+login') {
        $parsed.ErrorMessage = "Authentication expired: Portal returned login page."
        return $parsed
    }

    # 3. Check for receipt container
    if ($Html -notmatch '(?i)<div\s+id=["'']receipt["'']') {
        $parsed.ErrorMessage = "Missing expected report container element (<div id='receipt'>)."
        return $parsed
    }

    # 4. Check for title keyword
    if ($Html -notmatch '(?i)Bank Account Wise Balance Statement') {
        $parsed.ErrorMessage = "Report container missing expected title keyword: 'Bank Account Wise Balance Statement'."
        return $parsed
    }

    # 5. Extract dates
    if ($Html -match '(?i)From\s*Date\s*:(?:</strong>)?\s*(\d{2}/\d{2}/\d{4})') {
        $parsed.FromDate = $matches[1]
    }
    if ($Html -match '(?i)To\s*Date\s*:(?:</strong>)?\s*(\d{2}/\d{2}/\d{4})') {
        $parsed.ToDate = $matches[1]
    }

    # 6. Extract record count
    $trMatches = [regex]::Matches($Html, '(?si)<tr[^>]*>.*?</tr>')
    $rowCount = 0
    foreach ($tr in $trMatches) {
        $t = $tr.Value
        if ($t -notmatch '(?i)<th>' -and $t -match '(?i)<td>' -and $t -notmatch '(?i)table-pagination' -and $t -notmatch '(?i)tablesorter-filter-row') {
            $rowCount++
        }
    }
    $parsed.RecordCount = $rowCount

    # 7. Extract clean receipt HTML matching frontend PrintDiv
    $receiptStart = $Html.IndexOf('<div id="receipt"')
    if ($receiptStart -lt 0) { $receiptStart = $Html.IndexOf("<div id='receipt'") }

    if ($receiptStart -ge 0) {
        $sub = $Html.Substring($receiptStart)
        $btnIdx = $sub.IndexOf('<div class="text-center hidden-print')
        if ($btnIdx -gt 0) {
            $clean = $sub.Substring(0, $btnIdx)
        } else {
            $formIdx = $sub.IndexOf('</form>')
            if ($formIdx -gt 0) { $clean = $sub.Substring(0, $formIdx) } else { $clean = $sub }
        }

        # Strip pagination and interactive buttons
        $clean = [regex]::Replace($clean, '(?si)<div\s+class=["''][^"'']*table-pagination[^"'']*["'']>.*?</div>', '')
        $clean = [regex]::Replace($clean, '(?si)<div\s+class=["''][^"'']*ts-pager[^"'']*["'']>.*?</div>', '')
        $clean = [regex]::Replace($clean, '(?si)<button[^>]*>.*?</button>', '')
        $parsed.CleanHtml = $clean
    }

    $parsed.IsValid = $true
    $parsed.IsEmpty = ($rowCount -eq 0)
    return $parsed
}

function Build-StandaloneHtmlDocument {
    param(
        [string]$ReceiptHtml,
        [string]$Title = "Bank Account Wise Balance Statement"
    )

    $fullDoc = @"
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>$Title</title>
<style>
@page {
    size: A4 landscape;
    margin: 8mm 10mm 10mm 10mm;
}
body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 9pt;
    line-height: 1.25;
    color: #222;
    background: #fff;
    margin: 0;
    padding: 0;
}
h2, h3 {
    margin: 4px 0;
    text-align: center;
    font-weight: bold;
    color: #111;
}
h2 { font-size: 13pt; }
h3 { font-size: 11pt; }
p {
    margin: 3px 0;
    text-align: center;
    font-size: 8.5pt;
    color: #333;
}
.text-center { text-align: center; }
.text-right { text-align: right; }
.text-left { text-align: left; }
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
}
th, td {
    border: 1px solid #777;
    padding: 3px 5px;
    font-size: 8pt;
    vertical-align: middle;
}
th {
    background-color: #e8e8e8;
    color: #000;
    font-weight: bold;
    text-align: center;
}
td:nth-child(1) { text-align: center; width: 4%; }
td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9) {
    text-align: right;
    font-family: "Courier New", Courier, monospace;
    font-weight: 500;
}
.hidden-print, .table-pagination, .paging-nav, .remove-btn { display: none !important; }
</style>
</head>
<body>
$ReceiptHtml
</body>
</html>
"@
    return $fullDoc
}

# ==============================================================================
# 6. PDF EXPORT (WINDOWS 7 COMPATIBLE)
# ==============================================================================

function Convert-HtmlToPdf {
    param (
        [string]$HtmlPath,
        [string]$PdfPath
    )

    $browserCandidates = @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        "C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"
    )

    $foundBrowser = $null
    foreach ($b in $browserCandidates) {
        if (Test-Path $b) {
            $foundBrowser = $b
            break
        }
    }
    if (-not $foundBrowser) {
        $cmd = Get-Command "chrome.exe" -ErrorAction SilentlyContinue
        if (-not $cmd) { $cmd = Get-Command "msedge.exe" -ErrorAction SilentlyContinue }
        if ($cmd) { $foundBrowser = $cmd.Definition }
    }

    if ($foundBrowser) {
        $absHtml = [System.IO.Path]::GetFullPath($HtmlPath)
        $absPdf = [System.IO.Path]::GetFullPath($PdfPath)
        $fileUri = "file:///" + $absHtml.Replace("\", "/")
        $args = "--headless --disable-gpu --run-all-compositor-stages-before-draw --print-to-pdf=`"$absPdf`" `"$fileUri`""

        $p = Start-Process -FilePath $foundBrowser -ArgumentList $args -Wait -PassThru -NoNewWindow
        if (Test-Path $absPdf) {
            $item = Get-Item $absPdf
            if ($item.Length -gt 1024) {
                return $absPdf
            }
        }
    }

    # Fallback to wkhtmltopdf
    $wkCandidates = @(
        "C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
        "C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe"
    )
    $foundWk = $null
    foreach ($w in $wkCandidates) {
        if (Test-Path $w) { $foundWk = $w; break }
    }
    if (-not $foundWk) {
        $cmdWk = Get-Command "wkhtmltopdf.exe" -ErrorAction SilentlyContinue
        if ($cmdWk) { $foundWk = $cmdWk.Definition }
    }

    if ($foundWk) {
        $absHtml = [System.IO.Path]::GetFullPath($HtmlPath)
        $absPdf = [System.IO.Path]::GetFullPath($PdfPath)
        $args = "-O Landscape -s A4 `"$absHtml`" `"$absPdf`""
        $p = Start-Process -FilePath $foundWk -ArgumentList $args -Wait -PassThru -NoNewWindow
        if (Test-Path $absPdf) {
            $item = Get-Item $absPdf
            if ($item.Length -gt 1024) {
                return $absPdf
            }
        }
    }

    return $null
}

# ==============================================================================
# 7. DATE SEQUENCE ENGINE
# ==============================================================================

function Get-DateSequence {
    param (
        [string]$StartDateStr,
        [string]$EndDateStr,
        [switch]$WeekdaysOnly,
        [switch]$SkipSundays,
        [switch]$SkipSaturdays,
        [string[]]$ExcludeDates
    )

    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    $start = [DateTime]::ParseExact($StartDateStr, "dd/MM/yyyy", $culture)
    $end = [DateTime]::ParseExact($EndDateStr, "dd/MM/yyyy", $culture)

    if ($start -gt $end) {
        throw "Invalid date range: StartDate ($StartDateStr) cannot be after EndDate ($EndDateStr)."
    }

    $excludedSet = @()
    if ($ExcludeDates) {
        foreach ($d in $ExcludeDates) {
            if ($d) {
                $p = [DateTime]::ParseExact($d.Trim(), "dd/MM/yyyy", $culture)
                $excludedSet += $p.ToString("dd/MM/yyyy")
            }
        }
    }

    $list = @()
    $curr = $start
    while ($curr -le $end) {
        $formatted = $curr.ToString("dd/MM/yyyy")
        $dayOfWeek = $curr.DayOfWeek.ToString()
        $skipReason = $null

        if ($excludedSet -contains $formatted) {
            $skipReason = "Excluded specific holiday ($formatted)"
        } elseif ($WeekdaysOnly -and ($curr.DayOfWeek -eq [DayOfWeek]::Saturday -or $curr.DayOfWeek -eq [DayOfWeek]::Sunday)) {
            $skipReason = "Excluded weekend ($dayOfWeek)"
        } elseif ($SkipSundays -and $curr.DayOfWeek -eq [DayOfWeek]::Sunday) {
            $skipReason = "Excluded Sunday"
        } elseif ($SkipSaturdays -and $curr.DayOfWeek -eq [DayOfWeek]::Saturday) {
            $skipReason = "Excluded Saturday"
        }

        $item = New-Object PSObject
        $item | Add-Member -MemberType NoteProperty -Name "Date" -Value $curr
        $item | Add-Member -MemberType NoteProperty -Name "DateStr" -Value $formatted
        $item | Add-Member -MemberType NoteProperty -Name "FromDate" -Value $formatted
        $item | Add-Member -MemberType NoteProperty -Name "ToDate" -Value $formatted
        $item | Add-Member -MemberType NoteProperty -Name "DayOfWeek" -Value $dayOfWeek
        $item | Add-Member -MemberType NoteProperty -Name "IsIncluded" -Value ($skipReason -eq $null)
        $item | Add-Member -MemberType NoteProperty -Name "SkipReason" -Value $skipReason

        $list += $item
        $curr = $curr.AddDays(1)
    }
    return $list
}

function Trim-PdfToLastPage {
    param([string]$PdfPath)
    if (-not (Test-Path $PdfPath)) { return }
    $pyCmd = $null
    if (Get-Command "python3" -ErrorAction SilentlyContinue) {
        $pyCmd = "python3"
    } elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
        $pyCmd = "python"
    }
    if ($pyCmd) {
        $trimCode = "import pypdf; f=open(r'$PdfPath','rb'); r=pypdf.PdfReader(f); (open(r'$PdfPath','wb').write((lambda w: (w.add_page(r.pages[-1]), io.BytesIO())[1].getvalue())(pypdf.PdfWriter())) if len(r.pages)>1 else None) if hasattr(r,'pages') else None"
        $trimPy = @"
import pypdf, io
try:
    with open(r'$PdfPath', 'rb') as f:
        reader = pypdf.PdfReader(f)
        if len(reader.pages) > 1:
            writer = pypdf.PdfWriter()
            writer.add_page(reader.pages[-1])
            buf = io.BytesIO()
            writer.write(buf)
            data = buf.getvalue()
        else:
            data = None
    if data:
        with open(r'$PdfPath', 'wb') as f:
            f.write(data)
except Exception:
    pass
"@
        try {
            & $pyCmd -c $trimPy
        } catch {}
    }
}

function Download-DepositSlipPdf {
    param (
        [string]$TargetDateStr,
        [string]$DestinationPath,
        [string]$SessionCookie = "",
        [string]$BirtUrl = "https://kdmc.gov.in/birtPA/output",
        [int]$UlbName = 1,
        [int]$Ward = 4,
        [int]$Bank = 0,
        [string]$Mode = "X",
        [switch]$LastPageOnly = $true
    )

    $url = "$BirtUrl`?__report=DepositSlip_ReceiptDetailReport.rptdesign&__format=pdf&ULBName=$UlbName&Ward=$Ward&Bank=$Bank&Mode=$Mode&FromDate=$TargetDateStr&ToDate=$TargetDateStr"
    Log-Info "[$TargetDateStr] Fetching Deposit Slip from BIRT server (Ward $Ward - HO Main Branch)..."

    $request = [System.Net.HttpWebRequest]::Create($url)
    $request.Method = "GET"
    $request.Timeout = 60000
    $request.ReadWriteTimeout = 60000
    $request.UserAgent = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) Chrome/109.0.0.0"
    $request.Referer = "https://kdmc.gov.in/MainetService/AdminHome.html"

    $cookieJar = New-Object System.Net.CookieContainer
    if ($SessionCookie) {
        $request.Headers.Add("Cookie", "JSESSIONID=$SessionCookie")
        try {
            $c = New-Object System.Net.Cookie("JSESSIONID", $SessionCookie, "/", "kdmc.gov.in")
            $cookieJar.Add($c)
        } catch {}
    }
    $request.CookieContainer = $cookieJar

    $response = $null
    try {
        $response = $request.GetResponse()
    } catch [System.Net.WebException] {
        $webEx = $_.Exception
        if ($webEx.Response) {
            $response = $webEx.Response
        } else {
            throw $webEx
        }
    }

    $statusCode = [int]$response.StatusCode
    if ($statusCode -ne 200) {
        $response.Close()
        throw "Server returned HTTP status $statusCode"
    }

    $respStream = $response.GetResponseStream()
    $fileStream = [System.IO.File]::Create($DestinationPath)
    $buffer = New-Object byte[] 8192
    $totalBytes = 0
    while (($bytesRead = $respStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $fileStream.Write($buffer, 0, $bytesRead)
        $totalBytes += $bytesRead
    }
    $fileStream.Close()
    $respStream.Close()
    $response.Close()

    # Validate PDF signature
    if ($totalBytes -lt 1024) {
        Remove-Item $DestinationPath -Force -ErrorAction SilentlyContinue
        throw "Downloaded PDF is smaller than 1024 bytes ($totalBytes bytes)."
    }

    $magicBytes = [System.IO.File]::ReadAllBytes($DestinationPath)
    $magicStr = [System.Text.Encoding]::ASCII.GetString($magicBytes, 0, [Math]::Min(10, $magicBytes.Length))
    if (-not $magicStr.StartsWith("%PDF-")) {
        Remove-Item $DestinationPath -Force -ErrorAction SilentlyContinue
        throw "Server response is not a valid PDF (Header: $magicStr)."
    }

    if ($LastPageOnly) {
        Trim-PdfToLastPage -PdfPath $DestinationPath
    }

    return (Get-Item $DestinationPath).Length
}

function Download-PaymentSlipPdf {
    param (
        [string]$TargetDateStr,
        [string]$DestinationPath,
        [string]$SessionCookie = "",
        [string]$BirtUrl = "https://kdmc.gov.in/birtPA/output",
        [int]$UlbName = 1,
        [int]$Ward = 4,
        [int]$Bank = 0,
        [string]$PaymentMode = "0",
        [switch]$LastPageOnly = $true
    )

    $url = "$BirtUrl`?__report=DepositSlip_PaymentDetailReport.rptdesign&__format=pdf&ULBName=$UlbName&Ward=$Ward&Bank=$Bank&PaymentMode=$PaymentMode&FromDate=$TargetDateStr&ToDate=$TargetDateStr"
    Log-Info "[$TargetDateStr] Fetching Payment Slip from BIRT server (Ward $Ward - HO Main Branch)..."

    $request = [System.Net.HttpWebRequest]::Create($url)
    $request.Method = "GET"
    $request.Timeout = 60000
    $request.ReadWriteTimeout = 60000
    $request.UserAgent = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) Chrome/109.0.0.0"
    $request.Referer = "https://kdmc.gov.in/MainetService/AdminHome.html"

    $cookieJar = New-Object System.Net.CookieContainer
    if ($SessionCookie) {
        $request.Headers.Add("Cookie", "JSESSIONID=$SessionCookie")
        try {
            $c = New-Object System.Net.Cookie("JSESSIONID", $SessionCookie, "/", "kdmc.gov.in")
            $cookieJar.Add($c)
        } catch {}
    }
    $request.CookieContainer = $cookieJar

    $response = $null
    try {
        $response = $request.GetResponse()
    } catch [System.Net.WebException] {
        $webEx = $_.Exception
        if ($webEx.Response) {
            $response = $webEx.Response
        } else {
            throw $webEx
        }
    }

    $statusCode = [int]$response.StatusCode
    if ($statusCode -ne 200) {
        $response.Close()
        throw "Server returned HTTP status $statusCode"
    }

    $respStream = $response.GetResponseStream()
    $fileStream = [System.IO.File]::Create($DestinationPath)
    $buffer = New-Object byte[] 8192
    $totalBytes = 0
    while (($bytesRead = $respStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $fileStream.Write($buffer, 0, $bytesRead)
        $totalBytes += $bytesRead
    }
    $fileStream.Close()
    $respStream.Close()
    $response.Close()

    # Validate PDF signature
    if ($totalBytes -lt 1024) {
        Remove-Item $DestinationPath -Force -ErrorAction SilentlyContinue
        throw "Downloaded PDF is smaller than 1024 bytes ($totalBytes bytes)."
    }

    $magicBytes = [System.IO.File]::ReadAllBytes($DestinationPath)
    $magicStr = [System.Text.Encoding]::ASCII.GetString($magicBytes, 0, [Math]::Min(10, $magicBytes.Length))
    if (-not $magicStr.StartsWith("%PDF-")) {
        Remove-Item $DestinationPath -Force -ErrorAction SilentlyContinue
        throw "Server response is not a valid PDF (Header: $magicStr)."
    }

    if ($LastPageOnly) {
        Trim-PdfToLastPage -PdfPath $DestinationPath
    }

    return (Get-Item $DestinationPath).Length
}
