"""
Django settings for CryptoSight project

Configuration includes:
- Database settings (SQLite for development)
- Static and media file handling
- Installed apps (home, authuser, predict)
- Security settings (SECRET_KEY, DEBUG)
- ML model paths configuration
"""
from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url
import sys

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if it exists
env_path = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Read from environment with a safe default for local development
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key")

# SECURITY WARNING: don't run with debug turned on in production!
# Default to False if not in development
DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() == 'true'

# On Render, ensure DEBUG is False unless explicitly set
if os.getenv('RENDER'):
    DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() == 'true'

# ALLOWED_HOSTS configuration
# Read from environment variable, or use defaults
allowed_hosts_env = os.getenv("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(",") if host.strip()]

# Automatically allow Render domains if on Render
# Render sets RENDER=true and RENDER_EXTERNAL_HOSTNAME with the actual hostname
if os.getenv("RENDER"):
    # Allow the specific Render hostname if provided
    render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if render_hostname:
        if render_hostname not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(render_hostname)
        # Also extract and add the base domain (e.g., "onrender.com" from "xxx.onrender.com")
        # This helps with any subdomain variations
        if ".onrender.com" in render_hostname:
            # Add a pattern that covers the domain
            pass  # Django doesn't support wildcards, so we use the exact hostname
    # Allow localhost for internal health checks from within the container
    # This is needed for the startup script's curl test
    if "localhost" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append("localhost")
    # Also allow 127.0.0.1 for internal requests
    if "127.0.0.1" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append("127.0.0.1")

# For local development, allow localhost
if DEBUG:
    if "localhost" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.extend(["localhost", "127.0.0.1", "0.0.0.0"])

# Note: If ALLOWED_HOSTS is empty in production, Django will reject requests with DisallowedHost
# Make sure to set DJANGO_ALLOWED_HOSTS in Render dashboard or RENDER_EXTERNAL_HOSTNAME will be used


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'whitenoise.runserver_nostatic',  # Use whitenoise for static files
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'home',
    'authuser',
    'predict',
    'chatbot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Add whitenoise after security middleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'CryptoSight.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'CryptoSight.wsgi.application'


# Caching
# https://docs.djangoproject.com/en/4.2/topics/cache/

if os.getenv('REDIS_URL'):
    # Use Redis cache if available
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.getenv('REDIS_URL'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'SOCKET_CONNECT_TIMEOUT': 5,  # seconds
                'SOCKET_TIMEOUT': 5,  # seconds
                'IGNORE_EXCEPTIONS': True,  # don't raise exceptions on connection issues
            }
        }
    }
else:
    # Fallback to local memory cache
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'cryptosight-cache',
            'TIMEOUT': 300,  # 5 minutes
            'OPTIONS': {
                'MAX_ENTRIES': 1000
            }
        }
    }

# Session engine (use cache for session storage)
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

# Use SQLite for development, PostgreSQL for production
if 'test' in sys.argv or 'test_coverage' in sys.argv or os.getenv('USE_SQLITE', 'False').lower() == 'true':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }
else:
    # Use PostgreSQL on Render
    DATABASES = {
        'default': dj_database_url.config(
            default=os.getenv('DATABASE_URL'),
            conn_max_age=600,
            conn_health_checks=True,
        )
    }


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

# Set timezone to Asia/Kolkata (IST)
TIME_ZONE = 'Asia/Kolkata'

# Enable timezone support
USE_TZ = True
USE_I18N = True
USE_L10N = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Enable WhiteNoise for static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files (user uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Ensure the media directory exists
os.makedirs(MEDIA_ROOT, exist_ok=True)


# ML Model Paths
MODEL_DIR = os.path.join(BASE_DIR, '..', 'Model_Training')

# Ensure model directory exists
os.makedirs(MODEL_DIR, exist_ok=True)

# Configure model paths for different timeframes
MODEL_PATHS = {
    'hourly': {
        'model_dir': os.path.join(MODEL_DIR, 'models_hourly'),
        'scaler_suffix': '_hourly_scaler.pkl',
        'model_suffix': '_hourly_lstm.keras',
    },
    'daily': {
        'model_dir': os.path.join(MODEL_DIR, 'models_daily'),
        'scaler_suffix': '_daily_scaler.pkl',
        'model_suffix': '_daily_lstm.keras',
    },
}

# Create model directories if they don't exist
for config in MODEL_PATHS.values():
    os.makedirs(config['model_dir'], exist_ok=True)


# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security settings for production
if not DEBUG:
    # Security middleware settings
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    
    # Session settings
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    
    # HSTS settings (uncomment these in production after confirming HTTPS works)
    # SECURE_HSTS_SECONDS = 31536000  # 1 year
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # SECURE_HSTS_PRELOAD = True
    
    # Other security settings
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'
    
    # Configure trusted origins for CSRF
    CSRF_TRUSTED_ORIGINS = [
        'https://*.onrender.com',
        'https://cryptosight.onrender.com',
        'http://localhost:8000',
        'http://127.0.0.1:8000',
    ]
    
    # Add any custom domain here
    if os.getenv('CUSTOM_DOMAIN'):
        CSRF_TRUSTED_ORIGINS.append(f'https://{os.getenv("CUSTOM_DOMAIN")}')


# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'predict': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Celery configuration removed - Using synchronous execution for Render
