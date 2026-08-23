from rest_framework import status
from rest_framework.views import APIView

from apps.platform.portfolio.models import InventoryVehicle
from apps.platform.portfolio.serializers import PublicInventoryVehicleSerializer
from apps.platform.tenants.models import Tenant
from core.utils.api_response import error_response, success_response


class PublicInventoryVehiclesAPIView(APIView):
    """
    Public endpoint — no authentication required.

    Accepts the subdomain portion of the tenant's domain (e.g. "chezhiyancars")
    and returns the tenant's AVAILABLE inventory listings for a public showroom page.

    Domain matching mirrors PublicTenantBrandingAPIView: the DB stores full domains
    such as "chezhiyancars.vehubpro.com", so we query domain__istartswith="<subdomain>."
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request, domain: str):
        domain = domain.strip().lower()
        if not domain:
            return error_response(
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
            return error_response(
                request,
                code="TENANT_NOT_FOUND",
                message="No active tenant found for the given domain.",
                error="Tenant not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        queryset = InventoryVehicle.objects.select_related(
            "brand", "vehicle_model", "vehicle_type", "fuel_type"
        ).prefetch_related("key_features").filter(
            tenant=tenant,
            status=InventoryVehicle.STATUS_AVAILABLE,
            is_archived=False,
        ).order_by("-created_at")

        limit_param = request.query_params.get("limit")
        if limit_param:
            try:
                limit = max(1, min(int(limit_param), 100))
                queryset = queryset[:limit]
            except ValueError:
                pass

        serializer = PublicInventoryVehicleSerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Inventory vehicles retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )
