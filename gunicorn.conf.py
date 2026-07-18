"""Gunicorn config for production (VPS).

    gunicorn -c gunicorn.conf.py app.main:app

Uses uvicorn workers so the async app runs correctly. Tune `workers` to your
CPU count. If you run more than one worker, set REDIS_URL in .env so the rate
limiter is shared across workers.
"""
import multiprocessing
import os

bind = os.getenv("BIND", "0.0.0.0:8000")
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"      # stdout
errorlog = "-"       # stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()
forwarded_allow_ips = "*"  # trust the reverse proxy (nginx/Cloudflare) for X-Forwarded-*
