# Delhi HC Case Tracker — Windows dev setup.
#
# Usage:   .\scripts\dev\setup.ps1
#
# Idempotent: re-run anytime. Creates .venv, installs deps, copies .env,
# initialises the SQLite DB. Does NOT start servers — use `docker compose`
# or run uvicorn / `npm run dev` directly after this.

$ErrorActionPreference = "Stop"

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

Write-Host "==> Copying .env.example to .env (if missing)" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "    Created .env — edit it before running anything in production." -ForegroundColor Yellow
}

Write-Host "==> Initialising SQLite + applying Alembic migrations" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "backend\data" | Out-Null
Push-Location backend
& .venv\Scripts\python.exe -m alembic upgrade head
Pop-Location

Write-Host "==> Installing frontend npm deps" -ForegroundColor Cyan
Push-Location frontend
if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
}
Pop-Location

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next:"
Write-Host "  Backend:  .\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend"
Write-Host "  Frontend: cd frontend; npm run dev"
Write-Host "  Or both:  docker compose -f infrastructure\docker-compose.yml up --build"
