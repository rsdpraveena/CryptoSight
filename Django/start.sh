#!/bin/bash
# Start script to run Gunicorn, Celery worker, and Celery Beat
# Optimized for Render free plan

set -e

cd "$(dirname "$0")"

echo "=========================================="
echo "Starting CryptoSight Deployment"
echo "=========================================="

# Verify Redis connection
echo "[0/4] Verifying Redis connection..."
if [ -z "$REDIS_URL" ]; then
    echo "✗ ERROR: REDIS_URL environment variable is not set!"
    echo "   Please configure Redis service in render.yaml"
    exit 1
fi
echo "✓ Redis URL configured: ${REDIS_URL:0:20}..." # Show first 20 chars only

# Get PORT early - Render sets this dynamically
PORT=${PORT:-10000}
echo "  → Using PORT: $PORT"

# Run migrations (this loads TensorFlow, so it takes time)
echo "[1/4] Running database migrations..."
python manage.py migrate --noinput
echo "✓ Migrations complete"

# Create necessary directories
mkdir -p /tmp/celery

# Function to handle shutdown
cleanup() {
    echo ""
    echo "=========================================="
    echo "Shutting down services..."
    echo "=========================================="
    kill $CELERY_WORKER_PID 2>/dev/null || true
    kill $CELERY_BEAT_PID 2>/dev/null || true
    kill $GUNICORN_PID 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Start Gunicorn in background FIRST to bind port quickly for Render's health check
echo "[2/4] Starting Gunicorn web server (binding port $PORT)..."
gunicorn CryptoSight.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --workers 1 \
    --threads 2 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output \
    --pid /tmp/gunicorn.pid &
GUNICORN_PID=$!

# Wait for Gunicorn to actually bind the port and be ready
# Check if process is running and port is listening
echo "  → Waiting for Gunicorn to bind port $PORT..."
for i in {1..30}; do
    if ! kill -0 $GUNICORN_PID 2>/dev/null; then
        echo "✗ ERROR: Gunicorn process died during startup!"
        exit 1
    fi
    # Check if port is listening (using netstat or ss if available)
    if command -v ss >/dev/null 2>&1; then
        if ss -ln | grep -q ":$PORT "; then
            echo "✓ Gunicorn bound to port $PORT (verified with ss)"
            break
        fi
    elif command -v netstat >/dev/null 2>&1; then
        if netstat -ln 2>/dev/null | grep -q ":$PORT "; then
            echo "✓ Gunicorn bound to port $PORT (verified with netstat)"
            break
        fi
    fi
    # If we can't verify with tools, just wait a bit longer
    if [ $i -eq 30 ]; then
        echo "⚠ Warning: Could not verify port binding, but Gunicorn process is running"
    fi
    sleep 1
done

if ! kill -0 $GUNICORN_PID 2>/dev/null; then
    echo "✗ ERROR: Gunicorn failed to start!"
    exit 1
fi
echo "✓ Gunicorn started (PID: $GUNICORN_PID) - Port $PORT should be bound"

# Start Celery worker in background
echo "[3/4] Starting Celery worker..."
celery -A CryptoSight worker -l info --concurrency=2 --max-tasks-per-child=1 --logfile=/dev/stdout --pidfile=/tmp/celery/worker.pid &
CELERY_WORKER_PID=$!

# Wait and verify Celery worker started
sleep 3
if ! kill -0 $CELERY_WORKER_PID 2>/dev/null; then
    echo "✗ ERROR: Celery worker failed to start!"
    exit 1
fi
echo "✓ Celery worker started (PID: $CELERY_WORKER_PID)"

# Start Celery Beat in background
echo "[4/4] Starting Celery Beat scheduler..."
celery -A CryptoSight beat -l info --logfile=/dev/stdout --pidfile=/tmp/celery/beat.pid &
CELERY_BEAT_PID=$!

# Wait and verify Celery Beat started
sleep 2
if ! kill -0 $CELERY_BEAT_PID 2>/dev/null; then
    echo "✗ ERROR: Celery Beat failed to start!"
    exit 1
fi
echo "✓ Celery Beat started (PID: $CELERY_BEAT_PID)"

echo "=========================================="
echo "✓ All services started successfully!"
echo "  - Gunicorn: Running on port $PORT (PID: $GUNICORN_PID)"
echo "  - Celery Worker: PID $CELERY_WORKER_PID"
echo "  - Celery Beat: PID $CELERY_BEAT_PID"
echo "=========================================="
echo ""

# Keep the script alive and monitor Gunicorn (the main process)
# If Gunicorn dies, exit so Render can restart the service
while kill -0 $GUNICORN_PID 2>/dev/null; do
    sleep 5
done

echo "✗ Gunicorn process died, exiting..."
exit 1
