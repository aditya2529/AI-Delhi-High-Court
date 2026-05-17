# Lint Windows shell scripts (.ps1 / .psm1 / .psd1 / .bat / .cmd) for the
# encoding rules enforced in .gitattributes:
#
#   1. ASCII only. No em-dashes, en-dashes, smart quotes, ellipses, or any
#      other byte > 0x7F outside the leading UTF-8 BOM (0xEF 0xBB 0xBF).
#      Windows PowerShell 5.1 reads BOM-less files as Windows-1252 and
#      mis-parses any multi-byte UTF-8 sequence, so we keep .ps1 files
#      strictly ASCII to remove the foot-gun entirely.
#
#   2. .ps1 / .psm1 / .psd1 files MUST start with a UTF-8 BOM. This is
#      belt-and-braces: even if a contributor sneaks in a non-ASCII byte,
#      the BOM tells PS 5.1 to decode the file as UTF-8 and parse correctly.
#
#   3. .ps1 / .bat / .cmd files MUST use CRLF line endings.
#
# Usage:
#   pwsh -File scripts/dev/check-windows-scripts.ps1
#   powershell -File scripts/dev/check-windows-scripts.ps1     # PS 5.1 too
#
# Exits non-zero on the first violation it finds (after reporting them all).
# Safe to wire into a pre-commit hook or CI step.
#
# This script obeys its own rules: UTF-8 BOM, CRLF, ASCII only.

$ErrorActionPreference = "Stop"

# Walk from the repo root, not from the cwd, so the script works no matter
# where it is invoked from.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

$patterns = @("*.ps1", "*.psm1", "*.psd1", "*.bat", "*.cmd")
$files = @()
foreach ($pat in $patterns) {
    $files += Get-ChildItem -Path $repoRoot -Recurse -File -Filter $pat -ErrorAction SilentlyContinue |
        Where-Object {
            $rel = $_.FullName.Substring($repoRoot.Path.Length).TrimStart('\','/')
            # Skip vendored / generated trees.
            -not ($rel -like 'node_modules*' -or
                  $rel -like '*\node_modules\*' -or
                  $rel -like '.venv*' -or
                  $rel -like '*\.venv\*' -or
                  $rel -like '.git*' -or
                  $rel -like '*\.git\*')
        }
}

if ($files.Count -eq 0) {
    Write-Host "check-windows-scripts: no .ps1/.bat/.cmd files found under $repoRoot"
    exit 0
}

$violations = New-Object System.Collections.Generic.List[string]

foreach ($file in $files) {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $rel = $file.FullName.Substring($repoRoot.Path.Length).TrimStart('\','/')
    $ext = $file.Extension.ToLowerInvariant()

    # --- BOM check (PowerShell scripts only) -------------------------------
    $isPowerShell = ($ext -in @('.ps1', '.psm1', '.psd1'))
    $hasBom = ($bytes.Length -ge 3 -and
               $bytes[0] -eq 0xEF -and
               $bytes[1] -eq 0xBB -and
               $bytes[2] -eq 0xBF)

    if ($isPowerShell -and -not $hasBom) {
        $violations.Add("$rel : missing UTF-8 BOM (required for PowerShell 5.1 safety)")
    }

    # --- ASCII check (start past BOM if present) ---------------------------
    $start = if ($hasBom) { 3 } else { 0 }
    for ($i = $start; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -gt 0x7F) {
            # Compute 1-based line / column of the offending byte.
            $line = 1
            $col = 1
            for ($j = $start; $j -lt $i; $j++) {
                if ($bytes[$j] -eq 0x0A) { $line++; $col = 1 }
                else { $col++ }
            }
            $hex = "0x{0:X2}" -f $bytes[$i]
            $msg = "{0} : non-ASCII byte {1} at line {2} col {3} (ASCII only: -- for em-dash, straight quotes for smart quotes, ... for ellipsis)" -f $rel, $hex, $line, $col
            $violations.Add($msg)
            break  # one violation per file is enough; fix it and re-run
        }
    }

    # --- CRLF check (.ps1 / .bat / .cmd) -----------------------------------
    $needsCrlf = ($ext -in @('.ps1', '.psm1', '.psd1', '.bat', '.cmd'))
    if ($needsCrlf -and $bytes.Length -gt 0) {
        # If the file contains any LF that is NOT preceded by CR, it's not CRLF.
        $lfFound = $false
        $crlfBroken = $false
        for ($i = 0; $i -lt $bytes.Length; $i++) {
            if ($bytes[$i] -eq 0x0A) {
                $lfFound = $true
                if ($i -eq 0 -or $bytes[$i - 1] -ne 0x0D) {
                    $crlfBroken = $true
                    break
                }
            }
        }
        if ($lfFound -and $crlfBroken) {
            $violations.Add("$rel : line endings are not CRLF (re-save with CRLF; .gitattributes enforces this on checkout)")
        }
    }
}

if ($violations.Count -gt 0) {
    Write-Host ""
    Write-Host "check-windows-scripts: FAIL ($($violations.Count) violation(s))" -ForegroundColor Red
    foreach ($v in $violations) {
        Write-Host "  - $v" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Fix guide:" -ForegroundColor Yellow
    Write-Host "  1. Replace non-ASCII characters with ASCII equivalents."
    Write-Host "     em-dash -> --   en-dash -> -   smart quotes -> straight quotes   ellipsis -> ..."
    Write-Host "  2. Re-save .ps1 files as 'UTF-8 with BOM' and CRLF line endings."
    Write-Host "     VS Code: bottom-right -> 'Save with Encoding' -> 'UTF-8 with BOM'."
    Write-Host "                            -> click 'LF' next to it -> 'CRLF'."
    Write-Host "  3. Re-run this script."
    exit 1
}

Write-Host "check-windows-scripts: OK ($($files.Count) file(s) checked)" -ForegroundColor Green
exit 0
