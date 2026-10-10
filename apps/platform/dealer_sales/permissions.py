from rest_framework.permissions import BasePermission


class IsAuthenticatedDealerSalesAccess(BasePermission):
    """Matches every other app's permission class in this codebase (e.g.
    IsAuthenticatedPortfolioAccess) — just checks authentication. Real
    per-submodule granularity only drives frontend nav visibility
    (UserModuleNavAPIView), never gates the API itself, platform-wide."""

    message = "Authentication credentials were not provided or are invalid."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))
