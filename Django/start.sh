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

# Run migrations
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

# Start Celery worker in background
echo "[2/4] Starting Celery worker..."
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
echo "[3/4] Starting Celery Beat scheduler..."
celery -A CryptoSight beat -l info --logfile=/dev/stdout --pidfile=/tmp/celery/beat.pid &
CELERY_BEAT_PID=$!

# Wait and verify Celery Beat started
sleep 2
if ! kill -0 $CELERY_BEAT_PID 2>/dev/null; then
    echo "✗ ERROR: Celery Beat failed to start!"
    exit 1
fi
echo "✓ Celery Beat started (PID: $CELERY_BEAT_PID)"

# Start Gunicorn in foreground (keeps the service alive)
echo "[4/4] Starting Gunicorn web server..."

# Render sets PORT automatically via environment variable
# If not set, use default (shouldn't happen on Render)
PORT=${PORT:-10000}
echo "  → Binding to: 0.0.0.0:$PORT (PORT env: ${PORT})"
echo "  → Workers: 1, Threads: 2, Timeout: 120s"
echo "=========================================="
echo "✓ All services started successfully!"
echo "  - Gunicorn: Running on port $PORT"
echo "  - Celery Worker: PID $CELERY_WORKER_PID"
echo "  - Celery Beat: PID $CELERY_BEAT_PID"
echo "=========================================="
echo ""

# Start Gunicorn - this keeps the service alive
# Don't use --preload as it loads Django before forking, causing TensorFlow to load early
# The health check endpoint (/health/) will respond quickly without loading TensorFlow
exec gunicorn CryptoSight.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --workers 1 \
    --threads 2 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output
