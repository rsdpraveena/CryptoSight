import os
import time
import logging
import joblib
import psutil
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
from functools import lru_cache
from datetime import datetime, timedelta
from django.core.cache import cache

# Configure logging
logger = logging.getLogger(__name__)

# Global cache configuration
_MAX_CACHE_SIZE = 10  # Maximum number of models/scalers to cache
_CACHE_TTL = 3600  # 1 hour cache TTL
_MODEL_LOAD_RETRIES = 3
_MODEL_LOAD_DELAY = 1  # seconds

# In-memory cache with TTL tracking
_models_cache: Dict[str, Tuple[Any, float]] = {}
_scalers_cache: Dict[str, Tuple[Any, float]] = {}
_cache_stats = {
    'hits': 0,
    'misses': 0,
    'load_errors': 0,
    'last_cleared': datetime.now()
}

def _get_memory_usage() -> float:
    """Get current process memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)  # Convert to MB

def _cleanup_cache(cache_dict: Dict[str, Tuple[Any, float]]) -> None:
    """Remove expired items from cache."""
    current_time = time.time()
    expired_keys = [k for k, (_, timestamp) in cache_dict.items() 
                   if current_time - timestamp > _CACHE_TTL]
    
    for key in expired_keys:
        del cache_dict[key]
        logger.debug(f"Expired cache entry: {key}")

def get_model(model_name: str, timeframe: str, retries: int = _MODEL_LOAD_RETRIES) -> Any:
    """
    Lazy load and cache ML models with TTL and memory management.
    
    Args:
        model_name: Name of the model (e.g., 'BTC', 'ETH')
        timeframe: Timeframe for the model ('hourly' or 'daily')
        retries: Number of retry attempts for model loading
        
    Returns:
        Loaded TensorFlow model
        
    Raises:
        FileNotFoundError: If model file is not found
        RuntimeError: If model loading fails after retries
    """
    global _models_cache, _cache_stats
    
    # Clean up expired cache entries
    _cleanup_cache(_models_cache)
    
    cache_key = f"{model_name.lower()}_{timeframe.lower()}"
    
    # Check cache first
    if cache_key in _models_cache:
        model, _ = _models_cache[cache_key]
        _cache_stats['hits'] += 1
        logger.debug(f"Model cache hit: {cache_key}")
        return model
    
    _cache_stats['misses'] += 1
    logger.info(f"Loading model: {cache_key}")
    
    model_path = (
        Path(__file__).parent.parent / 
        'Model_Training' / 
        f'models_{timeframe}' / 
        f'{model_name.upper()}_{timeframe}_lstm.keras'
    )
    
    if not model_path.exists():
        error_msg = f"Model not found: {model_path}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    
    # Configure TensorFlow for optimal performance
    tf_config = tf.compat.v1.ConfigProto()
    tf_config.gpu_options.allow_growth = True  # Only allocate GPU memory as needed
    tf_config.intra_op_parallelism_threads = 1
    tf_config.inter_op_parallelism_threads = 1
    tf.keras.backend.set_session(tf.compat.v1.Session(config=tf_config))
    
    # Try loading with retries
    for attempt in range(1, retries + 1):
        try:
            mem_before = _get_memory_usage()
            start_time = time.time()
            
            # Load model with memory optimization
            model = tf.keras.models.load_model(
                str(model_path),
                compile=False,  # Don't compile until needed
                custom_objects=None,
                safe_mode=True
            )
            
            load_time = time.time() - start_time
            mem_after = _get_memory_usage()
            
            logger.info(
                f"Loaded model {cache_key} in {load_time:.2f}s. "
                f"Memory used: {mem_after - mem_before:.2f}MB"
            )
            
            # Update cache
            _models_cache[cache_key] = (model, time.time())
            
            # Enforce max cache size
            if len(_models_cache) > _MAX_CACHE_SIZE:
                oldest_key = min(_models_cache.keys(), 
                               key=lambda k: _models_cache[k][1])
                del _models_cache[oldest_key]
                logger.debug(f"Evicted model from cache: {oldest_key}")
            
            return model
            
        except Exception as e:
            if attempt == retries:
                error_msg = f"Failed to load model {cache_key} after {retries} attempts: {e}"
                logger.error(error_msg, exc_info=True)
                _cache_stats['load_errors'] += 1
                raise RuntimeError(error_msg) from e
                
            logger.warning(
                f"Attempt {attempt} failed for {cache_key}. "
                f"Retrying in {_MODEL_LOAD_DELAY}s... Error: {str(e)}"
            )
            time.sleep(_MODEL_LOAD_DELAY * attempt)

def get_scaler(model_name: str, timeframe: str) -> Any:
    """
    Lazy load and cache scalers with TTL.
    
    Args:
        model_name: Name of the model (e.g., 'BTC', 'ETH')
        timeframe: Timeframe for the scaler ('hourly' or 'daily')
        
    Returns:
        Loaded scaler object
    """
    global _scalers_cache
    
    # Clean up expired cache entries
    _cleanup_cache(_scalers_cache)
    
    cache_key = f"{model_name.lower()}_{timeframe.lower()}"
    
    # Check cache first
    if cache_key in _scalers_cache:
        scaler, _ = _scalers_cache[cache_key]
        _cache_stats['hits'] += 1
        return scaler
    
    _cache_stats['misses'] += 1
    logger.info(f"Loading scaler: {cache_key}")
    
    scaler_path = (
        Path(__file__).parent.parent / 
        'Model_Training' / 
        f'models_{timeframe}' / 
        f'{model_name.upper()}_scaler.pkl'
    )
    
    if not scaler_path.exists():
        error_msg = f"Scaler not found: {scaler_path}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    
    try:
        scaler = joblib.load(scaler_path)
        _scalers_cache[cache_key] = (scaler, time.time())
        
        # Enforce max cache size
        if len(_scalers_cache) > _MAX_CACHE_SIZE:
            oldest_key = min(_scalers_cache.keys(), 
                           key=lambda k: _scalers_cache[k][1])
            del _scalers_cache[oldest_key]
            logger.debug(f"Evicted scaler from cache: {oldest_key}")
            
        return scaler
        
    except Exception as e:
        error_msg = f"Failed to load scaler {cache_key}: {e}"
        logger.error(error_msg, exc_info=True)
        _cache_stats['load_errors'] += 1
        raise RuntimeError(error_msg) from e

def clear_model_cache() -> None:
    """Clear the model and scaler caches to free up memory."""
    global _models_cache, _scalers_cache, _cache_stats
    
    logger.info("Clearing model and scaler caches")
    
    # Clear TensorFlow session and models
    tf.keras.backend.clear_session()
    
    # Clear caches
    _models_cache.clear()
    _scalers_cache.clear()
    
    # Run garbage collection
    import gc
    gc.collect()
    
    _cache_stats['last_cleared'] = datetime.now()
    logger.info(f"Cache cleared. Memory usage: {_get_memory_usage():.2f}MB")

def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics and memory usage."""
    return {
        'model_cache_size': len(_models_cache),
        'scaler_cache_size': len(_scalers_cache),
        'hits': _cache_stats['hits'],
        'misses': _cache_stats['misses'],
        'load_errors': _cache_stats['load_errors'],
        'last_cleared': _cache_stats['last_cleared'].isoformat(),
        'memory_usage_mb': _get_memory_usage(),
        'cache_ttl_seconds': _CACHE_TTL
    }

def warmup_models() -> None:
    """Preload commonly used models to reduce first-time prediction latency."""
    logger.info("Warming up models...")
    start_time = time.time()
    
    common_models = [
        ('BTC', 'hourly'),
        ('ETH', 'hourly'),
        ('BNB', 'hourly'),
        ('BTC', 'daily'),
        ('ETH', 'daily')
    ]
    
    for model_name, timeframe in common_models:
        try:
            get_model(model_name, timeframe)
            get_scaler(model_name, timeframe)
            logger.debug(f"Warmed up {model_name} {timeframe}")
        except Exception as e:
            logger.warning(f"Failed to warm up {model_name} {timeframe}: {e}")
    
    logger.info(f"Model warmup completed in {time.time() - start_time:.2f}s")

# Initialize logging
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    warmup_models()