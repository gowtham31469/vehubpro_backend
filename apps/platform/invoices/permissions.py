from rest_framework.permissions import BasePermission


class IsAuthenticatedInvoiceAccess(BasePermission):
    """Allow any authenticated user scoped to a tenant (same pattern as other platform apps)."""

    message = "Authentication credentials were not provided or are invalid."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))
