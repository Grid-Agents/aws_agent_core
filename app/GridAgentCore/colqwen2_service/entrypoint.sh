#!/usr/bin/env sh
set -eu

if [ "$#" -eq 0 ] || [ "$1" = "serve" ]; then
  exec gunicorn \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers "${GUNICORN_WORKERS:-1}" \
    --threads "${GUNICORN_THREADS:-1}" \
    --timeout "${GUNICORN_TIMEOUT:-900}" \
    --access-logfile - \
    --error-logfile - \
    --log-level "${GUNICORN_LOG_LEVEL:-info}" \
    serve:app
fi

exec "$@"
