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

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(os.path.join(BASE_DIR, '.env'))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Read from environment with a safe default for local development
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"

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
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'home',
    'authuser',
    'predict',
    'chatbot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

# Use DATABASE_URL from environment (Render provides this automatically)
# Fallback to SQLite for local development
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + str(BASE_DIR / "db.sqlite3"))
DATABASES = {
    "default": dj_database_url.config(default=DATABASE_URL)
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

TIME_ZONE = 'Asia/Kolkata'  # Indian Standard Time (IST)

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ML Models path
# Reference models from Model_Training folder located alongside the Django project
MODELS_DIR = os.path.join(os.path.dirname(BASE_DIR), 'Model_Training')
DAILY_MODELS_PATH = os.path.join(MODELS_DIR, 'models_daily')
HOURLY_MODELS_PATH = os.path.join(MODELS_DIR, 'models_hourly')

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication URLs
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

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

# Celery Configuration
# Use REDIS_URL from environment so it works both locally and on Render
# Render provides Redis connection string in format: redis://:password@host:port
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# Ensure Redis URL has database number (default to 0 if not specified)
if REDIS_URL and not REDIS_URL.endswith('/0') and not REDIS_URL.endswith('/1'):
    if '/' not in REDIS_URL.split('@')[-1]:
        REDIS_URL = f"{REDIS_URL}/0"

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 10

# Celery Beat Scheduler Configuration
CELERY_BEAT_SCHEDULE = {
    'check-for-updates-every-5-minutes': {
        'task': 'check_and_update_all_pending_predictions',
        'schedule': 300.0,  # Run every 300 seconds (5 minutes)
        'args': (),
        'options': {'expires': 240.0}, # Task expires after 4 minutes
    },
}
