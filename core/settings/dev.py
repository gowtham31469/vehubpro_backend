"""Development settings."""
from .base import *  # noqa: F403,F401

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Development-friendly flags
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
