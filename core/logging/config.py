from __future__ import annotations

from pathlib import Path


def get_logging_config(base_dir: Path, log_level: str = "INFO") -> dict:
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {
                "()": "core.logging.handlers.RequestIdFilter",
            }
        },
        "formatters": {
            "json": {
                "()": "core.logging.formatters.JsonLogFormatter",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "filters": ["request_id"],
            },
            "app_file": {
                "class": "logging.FileHandler",
                "filename": str(log_dir / "app.log"),
                "formatter": "json",
                "filters": ["request_id"],
            },
            "error_file": {
                "class": "logging.FileHandler",
                "filename": str(log_dir / "error.log"),
                "formatter": "json",
                "filters": ["request_id"],
                "level": "ERROR",
            },
            "security_file": {
                "class": "logging.FileHandler",
                "filename": str(log_dir / "security.log"),
                "formatter": "json",
                "filters": ["request_id"],
            },
        },
        "loggers": {
            "django": {
                "handlers": ["console", "app_file", "error_file"],
                "level": log_level,
                "propagate": False,
            },
            "app.security": {
                "handlers": ["console", "security_file"],
                "level": "INFO",
                "propagate": False,
            },
            "app.audit": {
                "handlers": ["console", "security_file"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console", "app_file", "error_file"],
            "level": log_level,
        },
    }
