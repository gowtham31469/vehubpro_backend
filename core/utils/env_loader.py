"""Environment loading helpers for Django settings."""
from __future__ import annotations

import os
from pathlib import Path

import dotenv


def load_env_vars() -> None:
    """
    Load .env files from backend/config in layered order.

    Order:
    1) .env (shared defaults)
    2) .env.<env> where env is DJANGO_ENV (dev by default)
    """
    backend_dir = Path(__file__).resolve().parents[2]
    config_dir = backend_dir / "config"

    dotenv.load_dotenv(config_dir / ".env", override=False)

    env_name = os.getenv("DJANGO_ENV", "dev").strip().lower()
    env_file = config_dir / f".env.{env_name}"
    dotenv.load_dotenv(env_file, override=True)
