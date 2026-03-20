"""Tenant middleware scaffold for future multi-tenant support."""
from __future__ import annotations


class TenantMiddleware:
    """No-op scaffold for tenant resolution and routing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Placeholder: inject tenant context once tenancy strategy is defined.
        return self.get_response(request)
