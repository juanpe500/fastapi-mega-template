# Dev launcher (Windows). For production use gunicorn.conf.py on the VPS.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Write-Host "No .env found - copying .env.example -> .env"
    Copy-Item .env.example .env
}

if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

# Apply migrations (app also falls back to create_all on boot if this is skipped)
try { alembic upgrade head } catch { Write-Host "alembic upgrade skipped: $_" }

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
