from rest_framework.permissions import BasePermission


class IsCustomerRole(BasePermission):
    """Only a JWT belonging to a CUSTOMER-role user may access these endpoints."""

    message = "This endpoint is only available to customer accounts."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        role = getattr(user, "role", None)
        return getattr(role, "code", "") == "CUSTOMER"
