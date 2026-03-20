from __future__ import annotations

import logging

from core.logging.utils import mask_sensitive_data

logger = logging.getLogger("app.audit")


def log_audit_event(
    *,
    actor_id: str | None,
    actor_type: str,
    action: str,
    module: str,
    ip_address: str | None,
    method: str | None,
    endpoint: str | None,
    headers: dict | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    payload = {
        "actor_id": actor_id,
        "actor_type": actor_type,
        "action": action,
        "module": module,
        "ip_address": ip_address,
        "method": method,
        "endpoint": endpoint,
        "headers": mask_sensitive_data(headers or {}),
        "before": mask_sensitive_data(before or {}),
        "after": mask_sensitive_data(after or {}),
        "append_only": True,
        "retention_policy": "TODO: configure retention period as per compliance policy",
    }
    logger.info("audit_event", extra={"event": payload})
