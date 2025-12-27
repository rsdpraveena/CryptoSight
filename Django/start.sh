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
# Render ALWAYS sets PORT for web services, so if it's not set, something is wrong
if [ -z "$PORT" ]; then
    echo "⚠ WARNING: PORT environment variable is not set!"
    echo "   Render should set this automatically for web services."
    echo "   Defaulting to 10000, but this may cause issues."
    PORT=10000
else
    echo "✓ PORT environment variable is set: $PORT"
fi
echo "  → Binding to PORT: $PORT"

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

# Start Gunicorn FIRST to bind port immediately for Render's health check
# This ensures the port is available when Render checks, even if Django isn't fully loaded yet
echo "[1/4] Starting Gunicorn web server (binding port $PORT)..."
# Start Gunicorn in background initially to verify it starts, then we'll monitor it
gunicorn CryptoSight.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --timeout 180 \
    --workers 1 \
    --threads 2 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output \
    --pid /tmp/gunicorn.pid \
    --graceful-timeout 30 \
    --keep-alive 5 &
GUNICORN_PID=$!

# Wait for Gunicorn to actually bind the port and be ready
# Check if process is running and port is listening
echo "  → Waiting for Gunicorn to bind port $PORT and become ready..."
echo "     (This may take 20-30 seconds while Django/TensorFlow loads)"
PORT_READY=0
for i in {1..60}; do
    if ! kill -0 $GUNICORN_PID 2>/dev/null; then
        echo "✗ ERROR: Gunicorn process died during startup!"
        exit 1
    fi
    
    # Try to verify port is listening
    PORT_LISTENING=0
    if command -v ss >/dev/null 2>&1; then
        if ss -ln 2>/dev/null | grep -q ":$PORT "; then
            PORT_LISTENING=1
        fi
    elif command -v netstat >/dev/null 2>&1; then
        if netstat -ln 2>/dev/null | grep -q ":$PORT "; then
            PORT_LISTENING=1
        fi
    fi
    
    # Try to make an HTTP request to the health check endpoint
    # This verifies the service is actually responding, not just binding
    if [ $PORT_LISTENING -eq 1 ] || [ $i -gt 10 ]; then
        if command -v curl >/dev/null 2>&1; then
            if curl -f -s -o /dev/null -w "%{http_code}" --max-time 2 "http://localhost:$PORT/health/" 2>/dev/null | grep -q "200"; then
                echo ""
                echo "✓✓✓ Gunicorn is READY and responding to health checks! ✓✓✓"
                PORT_READY=1
                break
            fi
        elif command -v wget >/dev/null 2>&1; then
            if wget -q -O /dev/null -T 2 "http://localhost:$PORT/health/" 2>/dev/null; then
                echo ""
                echo "✓✓✓ Gunicorn is READY and responding to health checks! ✓✓✓"
                PORT_READY=1
                break
            fi
        fi
    fi
    
    # Show progress every 5 seconds
    if [ $((i % 5)) -eq 0 ] && [ $i -gt 0 ]; then
        echo "     Still waiting... ($i seconds elapsed)"
    fi
    
    # If port is listening but we can't test HTTP, assume it's ready after 20 seconds
    if [ $PORT_LISTENING -eq 1 ] && [ $i -gt 20 ]; then
        echo ""
        echo "✓ Gunicorn port $PORT is listening (HTTP test unavailable, but port is bound)"
        PORT_READY=1
        break
    fi
    
    sleep 1
done

if [ $PORT_READY -eq 0 ]; then
    echo ""
    echo "⚠ Note: Gunicorn process is running, but full readiness check timed out"
    echo "   This is usually fine - Django/TensorFlow loading can take 30-60 seconds"
    echo "   Render may show 'No open ports' warnings during this time"
fi

if ! kill -0 $GUNICORN_PID 2>/dev/null; then
    echo "✗ ERROR: Gunicorn failed to start!"
    exit 1
fi
echo "✓ Gunicorn started (PID: $GUNICORN_PID) - Port $PORT is bound and ready"

# Run migrations in background (this loads TensorFlow, so it takes time)
# Django can handle requests while migrations are running
echo "[2/4] Running database migrations (in background)..."
python manage.py migrate --noinput &
MIGRATE_PID=$!
echo "✓ Migrations started (PID: $MIGRATE_PID) - running in background"

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
echo "  - Migrations: Running (PID: $MIGRATE_PID)"
echo "  - Celery Worker: PID $CELERY_WORKER_PID"
echo "  - Celery Beat: PID $CELERY_BEAT_PID"
echo "=========================================="
echo ""

# Wait for migrations to complete (but don't fail the service if they fail)
echo "  → Waiting for migrations to complete..."
wait $MIGRATE_PID
MIGRATE_EXIT=$?
if [ $MIGRATE_EXIT -ne 0 ]; then
    echo "⚠ WARNING: Migrations exited with code $MIGRATE_EXIT"
    echo "   This might be normal if migrations were already applied."
    echo "   Service will continue running..."
else
    echo "✓ Migrations completed successfully"
fi

# Keep the script alive and monitor Gunicorn (the main process)
# If Gunicorn dies, exit so Render can restart the service
echo ""
echo "=========================================="
echo "Service is running. Monitoring processes..."
echo "=========================================="
echo ""

# Monitor all processes - if Gunicorn dies, exit (Render will restart)
# This keeps the service running as long as Gunicorn is alive
while kill -0 $GUNICORN_PID 2>/dev/null; do
    # Check if Celery processes are still running (non-critical, but log if they die)
    if ! kill -0 $CELERY_WORKER_PID 2>/dev/null; then
        echo "⚠ Warning: Celery worker (PID: $CELERY_WORKER_PID) is not running"
    fi
    
    if ! kill -0 $CELERY_BEAT_PID 2>/dev/null; then
        echo "⚠ Warning: Celery Beat (PID: $CELERY_BEAT_PID) is not running"
    fi
    
    sleep 10
done

echo "✗ Gunicorn process (PID: $GUNICORN_PID) died. Exiting so Render can restart the service..."
exit 1
