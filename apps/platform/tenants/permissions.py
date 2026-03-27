from rest_framework.permissions import BasePermission


class IsSuperAdminRole(BasePermission):
    message = "Only SUPER_ADMIN users can perform this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        role = getattr(user, "role", None)
        return bool(user.is_superuser and getattr(role, "code", "") == "SUPER_ADMIN")
