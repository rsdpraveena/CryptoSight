import os
import time
import logging
import joblib
import numpy as np
import pandas as pd
import requests
import tensorflow as tf
from datetime import datetime, timedelta
from functools import lru_cache
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Configure TensorFlow for better performance in production
tf.config.threading.set_intra_op_parallelism_threads(1)
tf.config.threading.set_inter_op_parallelism_threads(1)
tf.config.optimizer.set_jit(True)  # Enable XLA compilation

# Global cache for models and scalers with TTL (time-to-live)
_MODEL_CACHE = {}
_SCALER_CACHE = {}
_MODEL_LOAD_TIME = {}
_CACHE_TTL = 3600  # 1 hour cache TTL

@lru_cache(maxsize=32)
def get_live_data(symbol="BTC", interval="1h", usd_to_inr=88.75, retries=3, backoff_factor=0.5):
    """
    Fetch live market data from Binance API with caching and retry logic.
    
    Args:
        symbol (str): Cryptocurrency symbol (e.g., 'BTC')
        interval (str): Time interval ('1h' for hourly, '1d' for daily)
        usd_to_inr (float): USD to INR conversion rate
        retries (int): Number of retry attempts
        backoff_factor (float): Backoff factor for retries
        
    Returns:
        pd.DataFrame: DataFrame with OHLCV data or None if failed
    """
    cache_key = f'binance_data_{symbol.lower()}_{interval}'
    cached_data = cache.get(cache_key)
    
    if cached_data is not None:
        return cached_data
    
    symbol_map = {
        "ADA": "ADAUSDT", "AVAX": "AVAXUSDT", "BNB": "BNBUSDT", "BTC": "BTCUSDT", 
        "DOGE": "DOGEUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"
    }
    pair = symbol_map.get(symbol.upper())
    
    if not pair:
        logger.warning(f"Unsupported symbol: {symbol}")
        return None
        
    limit = 100 if interval == "1d" else 100  # Increased limit for better model accuracy
    url = "https://api.binance.com/api/v3/klines"
    
    for attempt in range(retries):
        try:
            params = {
                "symbol": pair, 
                "interval": interval, 
                "limit": limit
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "num_trades", "taker_base", "taker_quote", "ignore"
            ])

            # Convert and clean data
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float) * usd_to_inr
                
            df["volume"] = df["volume"].astype(float)
            df.index = pd.to_datetime(df["close_time"], unit='ms')
            df_result = df[["open", "high", "low", "close", "volume"]]
            df_result.columns = ["Open", "High", "Low", "Close", "Volume"]
            
            # Cache the result for 5 minutes
            cache.set(cache_key, df_result, 300)
            return df_result
            
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                logger.error(f"Failed to fetch data for {symbol} after {retries} attempts: {e}")
                return None
                
            # Exponential backoff
            sleep_time = backoff_factor * (2 ** attempt)
            time.sleep(min(sleep_time, 5))  # Max 5 seconds
            continue
            
    return None

@lru_cache(maxsize=32)
def get_realtime_price(symbol="BTC", usd_to_inr=88.75, retries=3, backoff_factor=0.5):
    """
    Fetches the real-time price for a symbol from Binance ticker with caching and retry logic.
    
    Args:
        symbol (str): Cryptocurrency symbol (e.g., 'BTC')
        usd_to_inr (float): USD to INR conversion rate
        retries (int): Number of retry attempts
        backoff_factor (float): Backoff factor for retries
        
    Returns:
        dict: Dictionary with price, symbol, and timestamp or None if failed
    """
    cache_key = f'price_{symbol.lower()}'
    cached_price = cache.get(cache_key)
    
    if cached_price is not None:
        return cached_price
    
    symbol_map = {
        "ADA": "ADAUSDT", "AVAX": "AVAXUSDT", "BNB": "BNBUSDT", "BTC": "BTCUSDT", 
        "DOGE": "DOGEUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"
    }
    pair = symbol_map.get(symbol.upper())
    
    if not pair:
        logger.warning(f"Unsupported symbol for real-time price: {symbol}")
        return None

    url = "https://api.binance.com/api/v3/ticker/price"
    
    for attempt in range(retries):
        try:
            response = requests.get(url, params={"symbol": pair}, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            result = {
                "price": float(data["price"]) * usd_to_inr,
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "base_currency": "USDT",
                "target_currency": symbol,
                "last_updated": datetime.utcnow().isoformat()
            }
            
            # Cache the result for 30 seconds (shorter TTL for real-time data)
            cache.set(cache_key, result, 30)
            return result
            
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                logger.error(f"Failed to fetch price for {symbol} after {retries} attempts: {e}")
                return None
                
            # Exponential backoff
            sleep_time = backoff_factor * (2 ** attempt)
            time.sleep(min(sleep_time, 3))  # Max 3 seconds
            continue
    
    return None

def load_model_and_scaler(symbol="BTC", interval="1h"):
    """
    Load the LSTM model and scaler for a given symbol and interval with caching.
    
    Args:
        symbol (str): Cryptocurrency symbol (e.g., 'BTC')
        interval (str): Time interval ('1h' for hourly, '1d' for daily)
        
    Returns:
        tuple: (model, scaler) or (None, None) if loading fails
    """
    global _MODEL_CACHE, _SCALER_CACHE, _MODEL_LOAD_TIME
    
    # Normalize interval to match directory names
    interval = interval.replace('1', '').replace('ly', '')  # Convert '1h' to 'h'
    
    # Check cache first with TTL
    cache_key = f"{symbol.lower()}_{interval}"
    current_time = time.time()
    
    if cache_key in _MODEL_CACHE and cache_key in _SCALER_CACHE:
        # Check if cache is still valid
        if current_time - _MODEL_LOAD_TIME.get(cache_key, 0) < _CACHE_TTL:
            return _MODEL_CACHE[cache_key], _SCALER_CACHE[cache_key]
        # Clear expired cache
        else:
            del _MODEL_CACHE[cache_key]
            del _SCALER_CACHE[cache_key]
            _MODEL_LOAD_TIME.pop(cache_key, None)
    
    # Determine model and scaler paths
    model_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'Model_Training',
        f'models_{interval}ly'  # e.g., models_hourly, models_daily
    )
    
    model_filename = f'{symbol.upper()}_{interval}ly_lstm.keras'
    scaler_filename = f'{symbol.upper()}_scaler.pkl'
    
    model_path = os.path.join(model_dir, model_filename)
    scaler_path = os.path.join(model_dir, scaler_filename)
    
    if not os.path.exists(model_path):
        logger.error(f"Model not found: {model_path}")
        return None, None
        
    if not os.path.exists(scaler_path):
        logger.error(f"Scaler not found: {scaler_path}")
        return None, None
    
    try:
        # Clear any existing TensorFlow session to free up memory
        tf.keras.backend.clear_session()
        
        # Load model with memory optimization
        model = tf.keras.models.load_model(
            model_path,
            compile=False,  # Don't compile until needed
            custom_objects=None,
            safe_mode=True  # Extra safety checks
        )
        
        # Set a unique name to avoid model name conflicts
        model._name = f"{symbol}_{interval}_model"
        
        # Load scaler with memory efficiency
        scaler = joblib.load(scaler_path)
        
        # Update cache
        _MODEL_CACHE[cache_key] = model
        _SCALER_CACHE[cache_key] = scaler
        _MODEL_LOAD_TIME[cache_key] = current_time
        
        logger.info(f"Loaded model and scaler for {symbol} {interval}")
        return model, scaler
        
    except Exception as e:
        logger.error(f"Error loading model/scaler for {symbol} {interval}: {e}", exc_info=True)
        # Clear cache on error
        _MODEL_CACHE.pop(cache_key, None)
        _SCALER_CACHE.pop(cache_key, None)
        _MODEL_LOAD_TIME.pop(cache_key, None)
        return None, None

def get_live_prediction(symbol="BTC", interval="1h", steps_ahead=3, usd_to_inr=88.75):
    """
    Generate live prediction using the trained LSTM model with error handling and optimization.
    
    Args:
        symbol (str): Cryptocurrency symbol (e.g., 'BTC')
        interval (str): Time interval ('1h' for hourly, '1d' for daily)
        steps_ahead (int): Number of future steps to predict
        usd_to_inr (float): USD to INR conversion rate
        
    Returns:
        pd.DataFrame: DataFrame with predicted prices or None if prediction fails
    """
    cache_key = f'prediction_{symbol.lower()}_{interval}_{steps_ahead}'
    cached_prediction = cache.get(cache_key)
    
    if cached_prediction is not None:
        return cached_prediction
    
    logger.info(f"Generating prediction for {symbol} {interval} (steps={steps_ahead})")
    
    # Input validation
    if not symbol or not interval or steps_ahead < 1:
        logger.error("Invalid input parameters")
        return None
    
    # Load model and scaler
    model, scaler = load_model_and_scaler(symbol, interval)
    if model is None or scaler is None:
        logger.error(f"Failed to load model or scaler for {symbol} {interval}")
        return None
    
    # Get live data with retry logic
    max_retries = 3
    df = None
    
    for attempt in range(max_retries):
        df = get_live_data(symbol, interval, usd_to_inr)
        if df is not None and not df.empty:
            break
        logger.warning(f"Attempt {attempt + 1} failed to fetch live data for {symbol}")
        time.sleep(1)  # Short delay before retry
    
    if df is None or df.empty:
        logger.error(f"Failed to fetch live data for {symbol} after {max_retries} attempts")
        return None
    
    try:
        # Prepare data for prediction
        data = df[['Close']].values
        if len(data) < 30:  # Ensure we have enough data points
            logger.warning(f"Insufficient data points for {symbol} ({len(data)} < 30)")
            return None
        
        # Scale the data
        scaled_data = scaler.transform(data)
        
        # Get sequence length from model input shape
        sequence_length = model.input_shape[1] if hasattr(model, 'input_shape') else 60
        
        # Prepare sequence for prediction (use the most recent sequence)
        if len(scaled_data) < sequence_length:
            logger.error(f"Not enough data points for sequence length {sequence_length}")
            return None
            
        X = scaled_data[-sequence_length:].reshape(1, sequence_length, 1)
        
        # Make predictions for future steps
        predicted_prices = []
        current_sequence = X.copy()
        
        for _ in range(steps_ahead):
            # Predict next step
            next_step = model.predict(current_sequence, verbose=0)
            predicted_prices.append(next_step[0][0])
            
            # Update sequence for next prediction
            current_sequence = np.roll(current_sequence, -1, axis=1)
            current_sequence[0, -1, 0] = next_step[0][0]
        
        # Inverse transform predictions to original scale
        predicted_prices = np.array(predicted_prices).reshape(-1, 1)
        predicted_prices = scaler.inverse_transform(predicted_prices)
        
        # Create DataFrame with predicted values
        last_date = df.index[-1]
        freq = 'H' if interval == '1h' else 'D'
        
        future_dates = pd.date_range(
            start=last_date + pd.Timedelta(hours=1 if freq == 'H' else 24),
            periods=steps_ahead,
            freq=freq
        )
        
        pred_df = pd.DataFrame({
            'Open': np.nan,
            'High': np.nan,
            'Low': np.nan,
            'Close': predicted_prices.flatten(),
            'Volume': 0  # Volume is not predicted
        }, index=future_dates)
        
        # Cache the prediction for 5 minutes
        cache.set(cache_key, pred_df, 300)
        
        return pred_df
        
    except Exception as e:
        logger.error(f"Prediction failed for {symbol} {interval}: {e}", exc_info=True)
        return None

if __name__ == "__main__":
    import argparse
    
    # Set up argument parsing
    parser = argparse.ArgumentParser(description='CryptoSight Price Prediction')
    parser.add_argument('--symbol', type=str, default='BTC', help='Cryptocurrency symbol (default: BTC)')
    parser.add_argument('--interval', type=str, default='1h', choices=['1h', '1d'], 
                       help='Time interval (1h for hourly, 1d for daily)')
    parser.add_argument('--steps', type=int, default=24, help='Number of future steps to predict')
    parser.add_argument('--usd-to-inr', type=float, default=88.75, help='USD to INR conversion rate')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('prediction.log')
        ]
    )
    
    logger.info(f"Starting prediction for {args.symbol} {args.interval} (steps={args.steps})")
    
    try:
        # Run prediction
        start_time = time.time()
        prediction = get_live_prediction(
            symbol=args.symbol,
            interval=args.interval,
            steps_ahead=args.steps,
            usd_to_inr=args.usd_to_inr
        )
        elapsed = time.time() - start_time
        
        if prediction is not None:
            print("\nPrediction Results:")
            print(prediction)
            logger.info(f"Prediction completed in {elapsed:.2f} seconds")
        else:
            logger.error("Prediction failed")
            
    except KeyboardInterrupt:
        logger.info("Prediction interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        # Clean up TensorFlow session
        tf.keras.backend.clear_session()
    else:
        print("Prediction failed")
