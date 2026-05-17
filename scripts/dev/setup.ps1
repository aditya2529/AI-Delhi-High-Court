# Delhi HC Case Tracker -- Windows dev setup.
#
# Usage:   .\scripts\dev\setup.ps1
#
# Idempotent: re-run anytime. Creates .venv, installs deps, copies BOTH
# env-example files (root .env for backend, frontend/.env.local for Next.js),
# initialises the SQLite DB, then validates the env layout and warns if the
# default dev ports are busy. Does NOT start servers -- use `docker compose`
# or run uvicorn / `npm run dev` directly after this.
#
# This file is enforced to be UTF-8 with BOM + CRLF by .gitattributes. The
# linter at scripts/dev/check-windows-scripts.ps1 fails CI if anyone slips
# in a non-ASCII byte or LF line ending.

$ErrorActionPreference = "Stop"

# Resolve repo root from the script location so the script works no matter
# where it is invoked from.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repoRoot
try {

Write-Host "==> Checking Python 3.11+" -ForegroundColor Cyan
$pythonVersion = & python --version 2>&1
if ($LASTEXITCODE -ne 0) { throw "Python not found on PATH. Install Python 3.11+." }
Write-Host "    $pythonVersion"

Write-Host "==> Creating backend virtualenv at .\backend\.venv" -ForegroundColor Cyan
if (-not (Test-Path "backend\.venv")) {
    & python -m venv backend\.venv
}
& backend\.venv\Scripts\python.exe -m pip install --upgrade pip
& backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

Write-Host "==> Copying root .env.example to .env (backend vars)" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "    Created .env -- edit it before running anything in production." -ForegroundColor Yellow
} else {
    Write-Host "    .env already exists; not overwriting. Run check-env.ps1 to spot drift." -ForegroundColor DarkGray
}

Write-Host "==> Copying frontend\.env.example to frontend\.env.local (NEXT_PUBLIC_* vars)" -ForegroundColor Cyan
if (Test-Path "frontend\.env.example") {
    if (-not (Test-Path "frontend\.env.local")) {
        Copy-Item "frontend\.env.example" "frontend\.env.local"
        Write-Host "    Created frontend\.env.local." -ForegroundColor Yellow
        Write-Host "    Remember: NEXT_PUBLIC_CLIENT_MODE must match CLIENT_MODE in root .env." -ForegroundColor Yellow
    } else {
        Write-Host "    frontend\.env.local already exists; not overwriting." -ForegroundColor DarkGray
    }
} else {
    Write-Host "    frontend\.env.example missing; skipping frontend env copy." -ForegroundColor Red
}

Write-Host "==> Initialising SQLite + applying Alembic migrations" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "backend\data" | Out-Null
Push-Location backend
try {
    & .venv\Scripts\python.exe -m alembic upgrade head
} finally {
    Pop-Location
}

Write-Host "==> Installing frontend npm deps" -ForegroundColor Cyan
Push-Location frontend
try {
    if (-not (Test-Path "node_modules")) {
        if (Test-Path "package-lock.json") { npm ci } else { npm install }
    }
} finally {
    Pop-Location
}

# --- Post-install validation ------------------------------------------------
# env-drift exits non-zero if a key is missing, but we DO NOT propagate that
# as a setup failure because setup itself succeeded -- the operator just
# needs to edit two files. Port check is purely advisory.

Write-Host "==> Validating env files (root .env + frontend\.env.local)" -ForegroundColor Cyan
& powershell -NoProfile -File (Join-Path $PSScriptRoot "check-env.ps1")
$envCheckExit = $LASTEXITCODE
if ($envCheckExit -ne 0) {
    Write-Host "    check-env reported issues (exit $envCheckExit). Fix above, then re-run." -ForegroundColor Yellow
}

Write-Host "==> Checking dev ports (3000, 8000)" -ForegroundColor Cyan
$node = Get-Command node -ErrorAction SilentlyContinue
if ($null -ne $node) {
    & node (Join-Path $PSScriptRoot "check-ports.mjs")
} else {
    Write-Host "    node not on PATH; skipping port check (install Node 20+)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next:"
Write-Host "  Backend:  .\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend"
Write-Host "  Frontend: cd frontend; npm run dev"
Write-Host "  Or both:  docker compose -f infrastructure\docker-compose.yml up --build"
Write-Host ""
Write-Host "After pulling new commits: re-run .\scripts\dev\check-env.ps1 to spot new env vars." -ForegroundColor DarkCyan

} finally {
    Pop-Location
}
