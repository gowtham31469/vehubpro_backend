from rest_framework.permissions import BasePermission


class IsSuperAdminRole(BasePermission):
    """
    Access allowed only when:
    - user.is_superuser is True
    - user.role.code == "SUPER_ADMIN"
    """

    message = "Only SUPER_ADMIN users can perform this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        role = getattr(user, "role", None)
        role_code = getattr(role, "code", "")
        return bool(user.is_superuser and role_code == "SUPER_ADMIN")
