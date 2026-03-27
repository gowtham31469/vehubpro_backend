from rest_framework.permissions import BasePermission


class IsAuthenticatedCustomerAccess(BasePermission):
    message = "Authentication credentials were not provided or are invalid."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))


def is_super_admin(user) -> bool:
    role = getattr(user, "role", None)
    return bool(getattr(user, "is_superuser", False) and getattr(role, "code", "") == "SUPER_ADMIN")
