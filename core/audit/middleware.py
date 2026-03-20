from __future__ import annotations

from django.utils.deprecation import MiddlewareMixin

from core.audit.constants import AuditAction, AuditModule
from core.audit.service import log_audit_event


class AuditMiddleware(MiddlewareMixin):
    """
    Logs auth and mutating requests to the audit logger.
    Keep this append-only in downstream storage (SIEM/WORM).
    """

    def process_response(self, request, response):
        path = request.path or ""
        method = request.method

        should_audit = path.startswith("/api/") and method in {"POST", "PUT", "PATCH", "DELETE"}
        if not should_audit:
            return response

        action = AuditAction.UPDATE
        module = AuditModule.SYSTEM
        if "/auth/login/" in path:
            action = AuditAction.LOGIN
            module = AuditModule.AUTH
        elif "/auth/logout/" in path:
            action = AuditAction.LOGOUT
            module = AuditModule.AUTH
        elif method == "POST":
            action = AuditAction.CREATE
        elif method == "DELETE":
            action = AuditAction.DELETE

        user = getattr(request, "user", None)
        actor_id = str(user.id) if getattr(user, "is_authenticated", False) else None
        actor_type = "user" if actor_id else "system_or_anonymous"

        headers = {
            "user_agent": request.headers.get("User-Agent"),
            "x_request_id": request.headers.get("X-Request-ID"),
        }

        log_audit_event(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            module=module,
            ip_address=request.META.get("REMOTE_ADDR"),
            method=method,
            endpoint=path,
            headers=headers,
        )
        return response
