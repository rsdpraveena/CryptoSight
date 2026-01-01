try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except (ImportError, ModuleNotFoundError):
    # Celery is not installed, create a dummy app
    class DummyCelery:
        def task(self, *args, **kwargs):
            if len(args) == 1 and callable(args[0]):
                return args[0]
            return lambda f: f
    
    celery_app = DummyCelery()
    __all__ = ('celery_app',)
