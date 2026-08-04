"""Base Django settings shared by all environments."""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import environ

from core.logging.config import get_logging_config
from core.utils.env_loader import load_env_vars

load_env_vars()

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BASE_DIR = ROOT_DIR

env = environ.Env(
    DEBUG=(bool, False),
)

SECRET_KEY = env("SECRET_KEY", default="unsafe-dev-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "auditlog",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "apps.platform.modules",
    "apps.platform.masters",
    "apps.platform.tenants",
    "apps.platform.billing",
    "apps.platform.users",
    "apps.platform.customers",
    "apps.platform.vehicles",
    "apps.platform.services",
    "apps.platform.jobcards",
    "apps.platform.invoices",
    "apps.platform.dashboard",
    "apps.consent",
    "apps.portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.logging.utils.CorrelationIdMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.request_logging.RequestLoggingMiddleware",
    "core.audit.middleware.AuditMiddleware",
    "core.middleware.security_headers.SecurityHeadersMiddleware",
    "core.middleware.tenant_middleware.TenantMiddleware",
]

ROOT_URLCONF = "core.urls"

SUPERADMIN_DIST = BASE_DIR.parent / "superadmin" / "dist"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [SUPERADMIN_DIST],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="vehubpro"),
        "USER": env("DB_USER", default="postgres"),
        "PASSWORD": env("DB_PASSWORD", default="postgres"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# User-uploaded media (tenant branding, etc.)
MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(BASE_DIR / "media")))

# Public API base used to build absolute URLs for locally stored media
BASE_URL = env("BASE_URL", default="http://127.0.0.1:8000")

# LOCAL | S3
STORAGE_TYPE = env("STORAGE_TYPE", default="LOCAL").strip().upper()

AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_REGION = env("AWS_REGION", default="us-east-1")
AWS_S3_PRESIGN_EXPIRES_SECONDS = env.int("AWS_S3_PRESIGN_EXPIRES_SECONDS", default=3600)

# Branding uploads (png, jpg, jpeg, ico)
BRANDING_MAX_UPLOAD_BYTES = env.int("BRANDING_MAX_UPLOAD_BYTES", default=2 * 1024 * 1024)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"

INSTALLED_APPS += ["corsheaders"]
MIDDLEWARE.insert(1, "corsheaders.middleware.CorsMiddleware")
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
])
# Each tenant gets its own subdomain (e.g. https://mrcars.vehubpro.com) that must be
# allowed to call the shared API subdomain. A static CORS_ALLOWED_ORIGINS list would
# require a manual update + redeploy for every new tenant, so any subdomain of
# TENANT_DOMAIN_SUFFIX is allowed via regex instead.
TENANT_DOMAIN_SUFFIX = env.str("TENANT_DOMAIN_SUFFIX", default="vehubpro.com")
CORS_ALLOWED_ORIGIN_REGEXES = env.list("CORS_ALLOWED_ORIGIN_REGEXES", default=[
    rf"^https://([a-z0-9-]+\.)?{re.escape(TENANT_DOMAIN_SUFFIX)}$",
])
CORS_ALLOW_CREDENTIALS = True

LOGGING = get_logging_config(BASE_DIR, env("LOG_LEVEL", default="INFO"))

# Compliance readiness placeholders for future modules and controls.
COMPLIANCE = {
    "gdpr_dpdp_enabled": env.bool("GDPR_DPDP_ENABLED", default=False),
    "iso27001_controls_enabled": env.bool("ISO27001_CONTROLS_ENABLED", default=False),
    "consent_audit_trail_required": env.bool("CONSENT_AUDIT_TRAIL_REQUIRED", default=False),
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "EXCEPTION_HANDLER": "core.utils.exception_handler.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=1)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
