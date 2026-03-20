"""Request logging middleware scaffold."""
from __future__ import annotations

import logging
import time

from core.logging.utils import mask_sensitive_data

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """Logs request metadata for traceability and audits."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = time.time()
        response = self.get_response(request)
        duration_ms = round((time.time() - started_at) * 1000, 2)
        request_payload = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            request_payload = mask_sensitive_data(getattr(request, "data", {}))
        logger.info(
            "request_completed",
            extra={
                "event": {
                    "method": request.method,
                    "path": request.get_full_path(),
                    "status": getattr(response, "status_code", "unknown"),
                    "duration_ms": duration_ms,
                    "request_payload": request_payload,
                }
            },
        )
        return response
