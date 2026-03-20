from __future__ import annotations

import uuid
from datetime import datetime, timezone

from rest_framework.response import Response


def _meta(request) -> dict:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    return {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def success_response(
    request,
    *,
    code: str,
    message: str,
    data,
    status_code: int,
) -> Response:
    return Response(
        {
            "success": True,
            "code": code,
            "message": message,
            "data": data,
            "error": None,
            "meta": _meta(request),
        },
        status=status_code,
    )


def error_response(
    request,
    *,
    code: str,
    message: str,
    error,
    status_code: int,
    data=None,
) -> Response:
    return Response(
        {
            "success": False,
            "code": code,
            "message": message,
            "data": data,
            "error": error,
            "meta": _meta(request),
        },
        status=status_code,
    )
