"""
Synchronous task implementations for CryptoSight.
These functions replace the Celery tasks for Render deployment.
"""
import os
import logging
import requests
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta
from .models import PredictionHistory

logger = logging.getLogger(__name__)

def generate_prediction_sync(user_id, crypto, timeframe, period):
    """
    Synchronous version of the prediction generation task.
    
    Args:
        user_id: ID of the user making the prediction
        crypto: Cryptocurrency symbol (e.g., 'BTC')
        timeframe: 'hourly' or 'daily'
        period: Number of periods to predict ahead
        
    Returns:
        dict: Prediction results
    """
    from django.contrib.auth.models import User
    from .views import get_prediction
    
    try:
        logger.info(f"🚀 Generating prediction: {crypto} | {timeframe} | {period} | user_id={user_id}")
        usd_to_inr = float(os.environ.get('USD_TO_INR', '88.75'))
        
        # Run prediction logic from views.py
        prediction_data = get_prediction(crypto, timeframe, int(period))

        # If user exists and is authenticated, store result in PredictionHistory
        if user_id > 0:
            user = User.objects.filter(id=user_id).first()
            if user:
                # Calculate the target time for the prediction
                target_time = timezone.now() + timedelta(
                    hours=period if timeframe == 'hourly' else period * 24
                )
                
                history_entry = PredictionHistory.objects.create(
                    user=user,
                    crypto=crypto,
                    timeframe=timeframe,
                    period=period,
                    current_price=prediction_data['current_price'],
                    predicted_price=prediction_data['predicted_price'],
                    confidence_level=prediction_data['confidence_level'],
                    market_sentiment=prediction_data['market_sentiment'],
                    prediction_target_time=target_time
                )
                logger.info(f"✅ Prediction saved in DB (ID: {history_entry.id})")
        
        # Return the complete prediction data
        return {
            'status': 'success',
            'crypto': prediction_data['crypto'],
            'timeframe': prediction_data['timeframe'],
            'period': prediction_data['period'],
            'current_price': prediction_data['current_price'],
            'predicted_price': prediction_data['predicted_price'],
            'confidence_level': prediction_data['confidence_level'],
            'market_sentiment': prediction_data['market_sentiment'],
            'timestamps': prediction_data['timestamps'],
            'historical_prices': prediction_data['historical_prices'],
            'predicted_prices': prediction_data['predicted_prices'],
            'min_price': prediction_data.get('min_price', prediction_data['predicted_price'] * 0.95),
            'max_price': prediction_data.get('max_price', prediction_data['predicted_price'] * 1.05),
            'volatility': prediction_data.get('volatility', 'Medium')
        }

    except Exception as e:
        logger.error(f"❌ Error in prediction: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {'status': 'error', 'message': str(e)}

def update_actual_price(prediction):
    """
    Update the actual price for a single prediction.
    
    Args:
        prediction: PredictionHistory instance to update
        
    Returns:
        bool: True if updated, False otherwise
    """
    try:
        # Skip if actual price already exists
        if prediction.actual_price:
            return False
            
        # Check if target time has been reached
        if not prediction.is_prediction_time_reached():
            return False
            
        usd_to_inr = float(os.environ.get('USD_TO_INR', '88.75'))
        symbol = f"{prediction.crypto}USDT"
        interval = "1h" if prediction.timeframe == 'hourly' else "1d"
        
        # Round down the target time to the start of the hour/day
        target_dt_utc = prediction.prediction_target_time.astimezone(timezone.utc)
        target_dt = target_dt_utc
        
        if interval == "1h":
            start_dt = target_dt.replace(minute=0, second=0, microsecond=0)
        else:  # "1d"
            start_dt = target_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            
        start_timestamp_ms = int(start_dt.timestamp() * 1000)
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start_timestamp_ms}&limit=1"
        
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                close_price_usd = float(data[0][4])
                price_inr = close_price_usd * usd_to_inr
                prediction.actual_price = round(price_inr, 2)
                prediction.save(update_fields=['actual_price'])
                logger.info(f"✅ Updated actual price for {prediction.crypto} (ID: {prediction.id}): ₹{price_inr:.2f}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"❌ Error updating prediction ID {prediction.id}: {str(e)}")
        return False

def check_and_update_pending_predictions():
    """
    Check for predictions that need actual price updates.
    This should be called from views that display prediction history.
    """
    # Find predictions where the actual price is not yet set and target time has passed
    pending_predictions = PredictionHistory.objects.filter(
        actual_price__isnull=True,
        prediction_target_time__lte=timezone.now()
    )
    
    updated_count = 0
    for prediction in pending_predictions:
        if update_actual_price(prediction):
            updated_count += 1
            
    if updated_count > 0:
        logger.info(f"📊 Updated {updated_count} actual prices")
        
    return updated_count
