from rest_framework.permissions import BasePermission


class IsAuthenticatedServiceAccess(BasePermission):
    message = "Authentication credentials were not provided or are invalid."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))
