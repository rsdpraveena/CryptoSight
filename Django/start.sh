#!/bin/bash
# Start script to run Gunicorn and Celery worker in the same process
# Optimized for Render free plan

set -e

cd "$(dirname "$0")"

echo "=========================================="
echo "Starting CryptoSight Deployment"
echo "=========================================="

# Run migrations
echo "[1/3] Running database migrations..."
python manage.py migrate --noinput
echo "✓ Migrations complete"

# Function to handle shutdown
cleanup() {
    echo ""
    echo "=========================================="
    echo "Shutting down services..."
    echo "=========================================="
    kill $CELERY_WORKER_PID 2>/dev/null || true
    kill $GUNICORN_PID 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Start Celery worker in background
echo "[2/3] Starting Celery worker..."
celery -A CryptoSight worker -l info --concurrency=2 --max-tasks-per-child=1 --logfile=/dev/stdout --pidfile=/tmp/celery.pid &
CELERY_WORKER_PID=$!

# Wait and verify Celery started
sleep 3
if ! kill -0 $CELERY_WORKER_PID 2>/dev/null; then
    echo "✗ ERROR: Celery worker failed to start!"
    exit 1
fi
echo "✓ Celery worker started (PID: $CELERY_WORKER_PID)"

# Start Gunicorn in foreground (keeps the service alive)
echo "[3/3] Starting Gunicorn web server..."
PORT=${PORT:-10000}
echo "  → Binding to port: $PORT"
echo "  → Workers: 1, Threads: 2, Timeout: 120s"
echo "=========================================="
echo "✓ All services started successfully!"
echo "=========================================="
echo ""

exec gunicorn CryptoSight.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --workers 1 \
    --threads 2 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
