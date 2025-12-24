#!/bin/bash
# Start script to run Gunicorn, Celery worker, and Celery beat in the same process
# This is needed for Render's free plan which doesn't support separate worker services

set -e

cd "$(dirname "$0")"

# Run migrations
python manage.py migrate --noinput

# Function to handle shutdown
cleanup() {
    echo "Shutting down..."
    kill $CELERY_WORKER_PID $CELERY_BEAT_PID $GUNICORN_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Start Celery worker in background
echo "Starting Celery worker..."
celery -A CryptoSight worker -l info &
CELERY_WORKER_PID=$!

# Start Celery beat in background  
echo "Starting Celery beat..."
celery -A CryptoSight beat -l info &
CELERY_BEAT_PID=$!

# Wait a moment for Celery to start
sleep 3

# Start Gunicorn in foreground (keeps the service alive)
echo "Starting Gunicorn..."
gunicorn CryptoSight.wsgi:application &
GUNICORN_PID=$!

# Wait for all processes
wait
