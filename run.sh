#!/usr/bin/env bash
# Dev launcher (Linux/macOS). For production use gunicorn.conf.py.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example -> .env"
  cp .env.example .env
fi

python -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

# Apply migrations (safe no-op if already up to date; app also self-heals on boot)
alembic upgrade head || echo "alembic upgrade skipped (will fall back to create_all on boot)"

exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
