# check-env.ps1 - diff .env files against their .env.example to spot drift.
#
# Background
# ----------
# The team's setup.ps1 copies *.env.example -> *.env once. After that, any
# subsequent commit that adds a new env var leaves existing developers with
# a stale .env and silently-defaulted (often wrong) behaviour. The founder
# hit exactly this with CLIENT_MODE during the first manual demo.
#
# After the Item-6 env layout split, this repo has two example/live pairs:
#   .env.example                  <-> .env                     (backend)
#   frontend/.env.example         <-> frontend/.env.local      (frontend)
#
# This script validates BOTH. It is non-destructive: it never writes to
# .env files. It only prints a diff and exits non-zero if any expected key
# is missing from the live file.
#
# Usage:
#   pwsh -File scripts/dev/check-env.ps1
#   powershell -File scripts/dev/check-env.ps1   # Windows PS 5.1 too
#
# Exit codes:
#   0 = all good
#   1 = at least one missing key (extras alone do NOT fail; they only warn)
#   2 = an .env.example was missing (configuration bug; tell the user)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

# Parse a dotenv-style file into the set of declared keys. We deliberately
# ignore values - drift in values is intentional (secrets, hostnames), but
# drift in *which keys exist* is the bug we are catching.
function Get-EnvKeys {
    param([string]$Path)
    $keys = New-Object System.Collections.Generic.HashSet[string]
    if (-not (Test-Path $Path)) { return $keys }
    foreach ($raw in [System.IO.File]::ReadAllLines($Path)) {
        $line = $raw.Trim()
        if ($line.Length -eq 0) { continue }
        if ($line.StartsWith("#")) { continue }
        # `export FOO=bar` is also valid dotenv syntax in some toolchains.
        if ($line.StartsWith("export ")) { $line = $line.Substring(7).TrimStart() }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { continue }
        $key = $line.Substring(0, $eq).Trim()
        if ($key.Length -gt 0) { [void]$keys.Add($key) }
    }
    return ,$keys
}

# Validate one example/live pair. Returns the count of missing keys.
function Test-EnvPair {
    param(
        [string]$Label,
        [string]$ExamplePath,
        [string]$LivePath
    )

    Write-Host ""
    Write-Host "=== $Label ===" -ForegroundColor Cyan
    Write-Host "  example: $ExamplePath"
    Write-Host "  live   : $LivePath"

    if (-not (Test-Path $ExamplePath)) {
        Write-Host "  ERROR: example file does not exist." -ForegroundColor Red
        return -1
    }
    if (-not (Test-Path $LivePath)) {
        Write-Host "  ERROR: live file does not exist. Run setup.ps1 first to create it." -ForegroundColor Red
        return -2
    }

    $expected = Get-EnvKeys -Path $ExamplePath
    $actual = Get-EnvKeys -Path $LivePath

    $missing = @($expected | Where-Object { -not $actual.Contains($_) } | Sort-Object)
    $extra = @($actual | Where-Object { -not $expected.Contains($_) } | Sort-Object)

    if ($missing.Count -eq 0 -and $extra.Count -eq 0) {
        Write-Host "  OK: $($actual.Count) keys, in sync with example." -ForegroundColor Green
        return 0
    }

    if ($missing.Count -gt 0) {
        Write-Host "  MISSING ($($missing.Count)) - in example but not in live file (defaults will apply):" -ForegroundColor Yellow
        foreach ($k in $missing) { Write-Host "    - $k" -ForegroundColor Yellow }
    }
    if ($extra.Count -gt 0) {
        Write-Host "  EXTRA ($($extra.Count)) - in live file but not in example (obsolete or local override):" -ForegroundColor DarkYellow
        foreach ($k in $extra) { Write-Host "    + $k" -ForegroundColor DarkYellow }
    }
    return $missing.Count
}

$rootMissing = Test-EnvPair `
    -Label "Backend env (root)" `
    -ExamplePath (Join-Path $repoRoot ".env.example") `
    -LivePath (Join-Path $repoRoot ".env")

# Frontend pair is optional - only validate if .env.example exists, since
# in older clones the frontend env file may not have been created yet.
$frontendExample = Join-Path $repoRoot "frontend\.env.example"
$frontendLive = Join-Path $repoRoot "frontend\.env.local"
$frontendMissing = 0
if (Test-Path $frontendExample) {
    $frontendMissing = Test-EnvPair `
        -Label "Frontend env (Next.js)" `
        -ExamplePath $frontendExample `
        -LivePath $frontendLive
} else {
    Write-Host ""
    Write-Host "=== Frontend env (Next.js) ===" -ForegroundColor Cyan
    Write-Host "  skipped: frontend/.env.example not found in this clone." -ForegroundColor DarkGray
    Write-Host "  (After the env-layout split, this file should exist; re-pull main.)" -ForegroundColor DarkGray
}

Write-Host ""
$exit = 0
if ($rootMissing -lt 0 -or $frontendMissing -lt 0) {
    # Missing example file is a configuration bug.
    $exit = 2
} elseif ($rootMissing -gt 0 -or $frontendMissing -gt 0) {
    $exit = 1
}

if ($exit -eq 0) {
    Write-Host "check-env: OK" -ForegroundColor Green
} else {
    Write-Host "check-env: FAIL (exit $exit)" -ForegroundColor Red
    Write-Host ""
    Write-Host "To resolve missing keys:" -ForegroundColor Yellow
    Write-Host "  Open the relevant .env / .env.local in an editor and add the missing"
    Write-Host "  keys from the matching .env.example. Copy the example value as a"
    Write-Host "  starting point, then edit for your environment."
}
exit $exit
