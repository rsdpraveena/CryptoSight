#!/bin/bash
# Start script to run Gunicorn and Celery worker in the same process
# Skipping Celery beat to save memory on free plan

set -e

cd "$(dirname "$0")"

# Run migrations
python manage.py migrate --noinput

# Function to handle shutdown
cleanup() {
    echo "Shutting down..."
    kill $CELERY_WORKER_PID $GUNICORN_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Start Celery worker in background with better logging
echo "Starting Celery worker..."
celery -A CryptoSight worker -l info --logfile=/tmp/celery.log --pidfile=/tmp/celery.pid &
CELERY_WORKER_PID=$!

# Wait a moment and check if Celery started
sleep 2
if ! kill -0 $CELERY_WORKER_PID 2>/dev/null; then
    echo "ERROR: Celery worker failed to start!"
    exit 1
fi

echo "Celery worker started with PID: $CELERY_WORKER_PID"

# Start Gunicorn in foreground (keeps the service alive)
echo "Starting Gunicorn..."
exec gunicorn CryptoSight.wsgi:application --timeout 120 --workers 1 --threads 2
