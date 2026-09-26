from rest_framework import status
from rest_framework.views import APIView

from apps.platform.services.models import ServiceCategory, ServiceItem
from apps.platform.services.serializers import PublicServiceCategorySerializer, PublicServiceItemSerializer
from apps.platform.tenants.models import Tenant
from core.utils.api_response import error_response, success_response


def _resolve_public_tenant(request, domain: str):
    """
    Resolve a tenant from the subdomain portion of its domain for public,
    no-auth endpoints. Returns (tenant, error_response); exactly one is None.

    Mirrors apps.platform.portfolio.public_views._resolve_public_tenant.
    """
    domain = domain.strip().lower()
    if not domain:
        return None, error_response(
            request,
            code="INVALID_DOMAIN",
            message="Domain parameter is required.",
            error="Missing domain.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    tenant = Tenant.objects.filter(
        domain__istartswith=f"{domain}.",
        status="active",
        is_archived=False,
    ).first()

    if tenant is None:
        return None, error_response(
            request,
            code="TENANT_NOT_FOUND",
            message="No active tenant found for the given domain.",
            error="Tenant not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return tenant, None


class PublicServiceCategoriesAPIView(APIView):
    """
    Public endpoint — no authentication required.

    Returns the tenant's active service categories for the public Services
    homepage's "Browse by Category" section.
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request, domain: str):
        tenant, error = _resolve_public_tenant(request, domain)
        if error:
            return error

        queryset = ServiceCategory.objects.filter(
            tenant=tenant,
            is_active=True,
            is_archived=False,
        ).order_by("sort_order", "name")

        serializer = PublicServiceCategorySerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service categories retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class PublicServiceItemsAPIView(APIView):
    """
    Public endpoint — no authentication required.

    Returns ALL of the tenant's active service items (not just featured
    ones) — the public Services homepage filters client-side for its
    "Popular Services" section, and groups by category for "Browse by
    Category", exactly like PublicPortfolio.jsx does for inventory vehicles.
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request, domain: str):
        tenant, error = _resolve_public_tenant(request, domain)
        if error:
            return error

        queryset = ServiceItem.objects.select_related("category").filter(
            tenant=tenant,
            is_active=True,
            is_archived=False,
        ).order_by("name")

        serializer = PublicServiceItemSerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service items retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )
