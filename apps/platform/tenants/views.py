from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.platform.tenants.models import Tenant, TenantBranding, TenantPII
from apps.platform.tenants.permissions import IsSuperAdminRole
from apps.platform.tenants.serializers import (
    PublicTenantBrandingSerializer,
    TenantBrandingSerializer,
    TenantPIISerializer,
    TenantSerializer,
)
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _is_archive_flag(request):
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


class TenantListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = Tenant.objects.filter(is_archived=_is_archive_flag(request)).order_by("name")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenants retrieved successfully.",
            data=build_paginated_data(request, queryset, TenantSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_CREATED",
            message="Tenant created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class TenantDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, request, pk):
        return get_object_or_404(Tenant, pk=pk, is_archived=_is_archive_flag(request))

    def get(self, request, pk):
        serializer = TenantSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant = self.get_object(request, pk)
        serializer = TenantSerializer(tenant, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_UPDATED",
            message="Tenant updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant = self.get_object(request, pk)
        serializer = TenantSerializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_UPDATED",
            message="Tenant updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        self.get_object(request, pk).archive()
        return success_response(
            request,
            code="TENANT_DELETED",
            message="Tenant deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class TenantBrandingByTokenAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = getattr(request.user, "tenant_id", None)
        if not tenant_id:
            return error_response(
                request,
                code="TENANT_CONTEXT_MISSING",
                message="Authenticated user is not mapped to a tenant.",
                error="Tenant association is required for this endpoint.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        branding = get_object_or_404(TenantBranding, tenant_id=tenant_id)
        serializer = TenantBrandingSerializer(branding)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant branding retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class TenantBrandingListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        queryset = TenantBranding.objects.select_related("tenant").all()
        tenant_id = request.query_params.get("tenant")
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant branding records retrieved successfully.",
            data=build_paginated_data(request, queryset, TenantBrandingSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TenantBrandingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_BRANDING_CREATED",
            message="Tenant branding created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class TenantBrandingDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self, pk):
        return get_object_or_404(TenantBranding, pk=pk)

    def get(self, request, pk):
        serializer = TenantBrandingSerializer(self.get_object(pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant branding retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        instance = self.get_object(pk)
        serializer = TenantBrandingSerializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_BRANDING_UPDATED",
            message="Tenant branding updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        instance = self.get_object(pk)
        serializer = TenantBrandingSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_BRANDING_UPDATED",
            message="Tenant branding updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return success_response(
            request,
            code="TENANT_BRANDING_DELETED",
            message="Tenant branding deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class TenantPIIListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = TenantPII.objects.select_related("tenant").all()
        tenant_id = request.query_params.get("tenant")
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant PII records retrieved successfully.",
            data=build_paginated_data(request, queryset, TenantPIISerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TenantPIISerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_PII_CREATED",
            message="Tenant PII created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class TenantPIIDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, pk):
        return get_object_or_404(TenantPII, pk=pk)

    def get(self, request, pk):
        serializer = TenantPIISerializer(self.get_object(pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant PII retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        instance = self.get_object(pk)
        serializer = TenantPIISerializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_PII_UPDATED",
            message="Tenant PII updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        instance = self.get_object(pk)
        serializer = TenantPIISerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="TENANT_PII_UPDATED",
            message="Tenant PII updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return success_response(
            request,
            code="TENANT_PII_DELETED",
            message="Tenant PII deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class PublicTenantBrandingAPIView(APIView):
    """
    Public endpoint — no authentication required.

    Accepts the subdomain portion of the tenant's domain (e.g. "chezhiyancars")
    and returns safe branding fields (logo URL, primary colour, business name).

    Domain matching: the DB stores full domains such as "chezhiyancars.vehubpro.com",
    so we query domain__istartswith="<subdomain>." to reconstruct the match without
    needing a hard-coded domain suffix setting.
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

        tenant = (
            Tenant.objects.filter(
                domain__istartswith=f"{domain}.",
                status="active",
                is_archived=False,
            )
            .select_related("branding")
            .first()
        )

        if tenant is None:
            return error_response(
                request,
                code="TENANT_NOT_FOUND",
                message="No active tenant found for the given domain.",
                error="Tenant not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            branding = tenant.branding
        except TenantBranding.DoesNotExist:
            # Tenant exists but branding record hasn't been created yet — return safe defaults.
            return success_response(
                request,
                code="DATA_RETRIEVED",
                message="Tenant branding retrieved successfully.",
                data={"logo_url": None, "primary_color": None, "business_name": tenant.name},
                status_code=status.HTTP_200_OK,
            )

        serializer = PublicTenantBrandingSerializer(branding)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant branding retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )
