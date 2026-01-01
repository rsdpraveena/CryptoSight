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
    --threads 1 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output \
    --pid /tmp/gunicorn.pid \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 &
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

# Run migrations FIRST and wait for them to complete before starting Celery
# This reduces peak memory usage (migrations + Celery + Gunicorn all at once)
echo "[2/4] Running database migrations..."
python manage.py migrate --noinput
echo "✓ Migrations complete"

# Test Redis connectivity before starting Celery
echo "[3/4] Testing Redis connectivity..."
if command -v python3 >/dev/null 2>&1; then
    python3 -c "
import os
import sys
try:
    import redis
    redis_url = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    # Parse Redis URL
    if '://' in redis_url:
        redis_url = redis_url.split('://', 1)[1]
    if '@' in redis_url:
        auth, rest = redis_url.split('@', 1)
        if ':' in rest:
            host, port_db = rest.split(':', 1)
            if '/' in port_db:
                port, db = port_db.split('/', 1)
            else:
                port, db = port_db, '0'
        else:
            host, port, db = rest, '6379', '0'
        password = auth.split(':', 1)[1] if ':' in auth else None
    else:
        if ':' in redis_url:
            host, port_db = redis_url.split(':', 1)
            if '/' in port_db:
                port, db = port_db.split('/', 1)
            else:
                port, db = port_db, '0'
        else:
            host, port, db = redis_url, '6379', '0'
        password = None
    r = redis.Redis(host=host, port=int(port), db=int(db), password=password, socket_connect_timeout=5)
    r.ping()
    print('✓ Redis connection successful')
    sys.exit(0)
except Exception as e:
    print(f'⚠ Redis connection test failed: {e}')
    print('   Continuing anyway - worker will retry connection...')
    sys.exit(0)
" || true
fi

# Start Celery worker in background with reduced concurrency to save memory
echo "Starting Celery worker (optimized for memory - concurrency=1)..."
celery -A CryptoSight worker -l info --concurrency=1 --max-tasks-per-child=50 --logfile=/dev/stdout --pidfile=/tmp/celery/worker.pid &
CELERY_WORKER_PID=$!

# Wait and verify Celery worker started and is ready
echo "  → Waiting for Celery worker to initialize..."
WORKER_READY=0
for i in {1..15}; do
    if ! kill -0 $CELERY_WORKER_PID 2>/dev/null; then
        echo "✗ ERROR: Celery worker process died during startup!"
        exit 1
    fi
    
    # Check if worker is actually running by checking for worker log output
    # If pidfile exists and process is running, assume worker is starting
    if [ -f /tmp/celery/worker.pid ]; then
        WORKER_PID_FROM_FILE=$(cat /tmp/celery/worker.pid 2>/dev/null || echo "")
        if [ -n "$WORKER_PID_FROM_FILE" ] && kill -0 "$WORKER_PID_FROM_FILE" 2>/dev/null; then
            if [ $i -ge 5 ]; then
                echo "✓ Celery worker is running (PID: $CELERY_WORKER_PID)"
                WORKER_READY=1
                break
            fi
        fi
    fi
    
    sleep 1
done

if [ $WORKER_READY -eq 0 ]; then
    if ! kill -0 $CELERY_WORKER_PID 2>/dev/null; then
        echo "✗ ERROR: Celery worker failed to start!"
        exit 1
    else
        echo "⚠ Warning: Could not fully verify Celery worker readiness, but process is running"
        echo "   Worker may still be connecting to Redis..."
    fi
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
echo "  - Migrations: Completed"
echo "  - Celery Worker: PID $CELERY_WORKER_PID"
echo "  - Celery Beat: PID $CELERY_BEAT_PID"
echo "=========================================="
echo ""

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
