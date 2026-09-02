import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only-change-me-before-any-real-deployment"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "jobs",
    "rota",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "jobs.context_processors.nav_extras",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 500 * 1024 * 1024

# Shared drive this computer can see. Leave empty to accept any local path.
# Example: [r"Z:\\Machining"]
SHARED_DRIVE_ROOTS = []

# Machining week starts Thursday. Friday–Sunday are not on the rota.
ROTA_WEEK_START_WEEKDAY = 3  # Thursday
ROTA_SKIP_WEEKDAYS = (4, 5, 6)  # Friday, Saturday, Sunday

# Incoming webhook for the shop Google Chat space. Leave empty to disable pings.
# Put the real URL in config/local_settings.py (gitignored), not here.
GOOGLE_CHAT_WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "")


def _running_tests():
    return len(sys.argv) > 1 and sys.argv[1] == "test"


def _load_local_settings():
    path = BASE_DIR / "config" / "local_settings.py"
    if not path.is_file():
        return
    namespace = {"__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), namespace)
    for key, value in namespace.items():
        if key.isupper():
            globals()[key] = value


# Shop secrets (webhook URL, emails). Skipped during tests.
if not _running_tests():
    _load_local_settings()
