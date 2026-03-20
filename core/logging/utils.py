from __future__ import annotations

import contextvars
import re
import uuid

from django.utils.deprecation import MiddlewareMixin

_request_id_ctx = contextvars.ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str:
    return _request_id_ctx.get()


def generate_request_id() -> str:
    return str(uuid.uuid4())


def mask_email(value: str) -> str:
    if "@" not in value:
        return value
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        masked = "*" * len(local)
    else:
        masked = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{masked}@{domain}"


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "***"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def mask_token(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def mask_sensitive_data(payload):
    if isinstance(payload, dict):
        masked = {}
        for key, value in payload.items():
            lower_key = key.lower()
            if isinstance(value, (dict, list)):
                masked[key] = mask_sensitive_data(value)
            elif "email" in lower_key and isinstance(value, str):
                masked[key] = mask_email(value)
            elif "phone" in lower_key and isinstance(value, str):
                masked[key] = mask_phone(value)
            elif any(k in lower_key for k in ["password", "token", "secret", "authorization"]):
                masked[key] = "***"
            else:
                masked[key] = value
        return masked
    if isinstance(payload, list):
        return [mask_sensitive_data(item) for item in payload]
    return payload


class CorrelationIdMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        request.request_id = request_id
        set_request_id(request_id)

    def process_response(self, request, response):
        request_id = getattr(request, "request_id", get_request_id())
        response["X-Request-ID"] = request_id
        return response
