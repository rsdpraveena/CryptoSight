from __future__ import absolute_import, unicode_literals
import os
import logging
from celery import Celery
from celery.signals import worker_ready

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CryptoSight.settings")

app = Celery("CryptoSight")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Get Redis URL from environment or Django settings
redis_url = os.getenv("REDIS_URL")
if not redis_url:
    from django.conf import settings
    redis_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')

# Ensure Redis URL has database number
if redis_url and not redis_url.endswith('/0') and not redis_url.endswith('/1'):
    if '/' not in redis_url.split('@')[-1]:
        redis_url = f"{redis_url}/0"

app.conf.broker_url = redis_url
app.conf.result_backend = redis_url

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery is working"""
    print(f'Request: {self.request!r}')


# Warm-up hook: DISABLED to save memory on Render free tier
# Models will be loaded on-demand when needed (lazy loading)
# This prevents memory exhaustion during startup
@worker_ready.connect
def warmup_models(sender=None, **kwargs):
    logger = logging.getLogger(__name__)
    # Disable model warm-up on Render to save memory (512MB limit)
    if os.getenv("RENDER"):
        logger.info("Model warm-up disabled on Render to conserve memory. Models will load on-demand.")
        return
    
    # Only warm-up models in non-Render environments
    try:
        # Import here to avoid import overhead in Django process startup
        from predict.prediction import load_model_and_scaler, get_live_prediction

        symbols_to_prime = ["BTC"]
        intervals_to_prime = ["1h", "1d"]

        for symbol in symbols_to_prime:
            for interval in intervals_to_prime:
                model, scaler = load_model_and_scaler(symbol, interval)
                if model is None or scaler is None:
                    continue
                # Run a tiny forward-pass to prime TF runtime and caches
                try:
                    _ = get_live_prediction(symbol, interval, steps_ahead=1, usd_to_inr=float(os.environ.get('USD_TO_INR', '88.75')))
                except Exception:
                    # Prediction priming can fail if network is offline; that's fine
                    pass
        logger.info("Celery warm-up complete: models preloaded")
    except Exception as exc:
        logger.warning(f"Celery warm-up skipped: {exc}")
