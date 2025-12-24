# Lazy imports to avoid loading TensorFlow during Django startup/migrations
# Import these functions only when needed, not at module level

__all__ = ['get_live_data', 'get_live_prediction', 'load_model_and_scaler']

def _lazy_import():
    """Lazy import to avoid TensorFlow loading during Django initialization"""
    from .prediction import get_live_data, get_live_prediction, load_model_and_scaler
    return get_live_data, get_live_prediction, load_model_and_scaler

def get_live_data(*args, **kwargs):
    """Lazy wrapper for get_live_data"""
    from .prediction import get_live_data
    return get_live_data(*args, **kwargs)

def get_live_prediction(*args, **kwargs):
    """Lazy wrapper for get_live_prediction"""
    from .prediction import get_live_prediction
    return get_live_prediction(*args, **kwargs)

def load_model_and_scaler(*args, **kwargs):
    """Lazy wrapper for load_model_and_scaler"""
    from .prediction import load_model_and_scaler
    return load_model_and_scaler(*args, **kwargs)