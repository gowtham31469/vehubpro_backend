from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.platform.portfolio.models import InventoryFeature, InventoryVehicle
from apps.platform.portfolio.permissions import IsAuthenticatedPortfolioAccess
from apps.platform.portfolio.serializers import InventoryFeatureSerializer, InventoryVehicleSerializer
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _is_archive_flag(request):
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


def _tenant_context(request):
    tenant_id = getattr(request.user, "tenant_id", None)
    if not tenant_id:
        return None, error_response(
            request,
            code="TENANT_CONTEXT_MISSING",
            message="Authenticated user is not mapped to a tenant.",
            error="Tenant association is required for this endpoint.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return tenant_id, None


class InventoryVehicleListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedPortfolioAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = InventoryVehicle.objects.select_related("tenant", "brand", "vehicle_model", "vehicle_type", "fuel_type").prefetch_related("key_features").filter(
            tenant_id=tenant_id,
            is_archived=_is_archive_flag(request),
        ).order_by("-created_at")

        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(vehicle_model__name__icontains=search)

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Inventory vehicles retrieved successfully.",
            data=build_paginated_data(request, queryset, InventoryVehicleSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("tenant_id", None)

        serializer = InventoryVehicleSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="INVENTORY_VEHICLE_CREATED",
            message="Inventory vehicle created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class InventoryVehicleDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedPortfolioAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        queryset = InventoryVehicle.objects.select_related("tenant", "brand", "vehicle_model", "vehicle_type", "fuel_type").prefetch_related("key_features").filter(
            pk=pk,
            is_archived=_is_archive_flag(request),
        )
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        else:
            queryset = queryset.none()
        return get_object_or_404(queryset)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = InventoryVehicleSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Inventory vehicle retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("tenant_id", None)
        serializer = InventoryVehicleSerializer(
            instance, data=payload, partial=partial, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="INVENTORY_VEHICLE_UPDATED",
            message="Inventory vehicle updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        instance.archive()
        return success_response(
            request,
            code="INVENTORY_VEHICLE_DELETED",
            message="Inventory vehicle archived successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class InventoryFeatureListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedPortfolioAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = InventoryFeature.objects.filter(
            tenant_id=tenant_id, is_archived=_is_archive_flag(request)
        ).order_by("name")
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=str(is_active).strip().lower() in {"true", "1", "yes"})
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Inventory features retrieved successfully.",
            data=build_paginated_data(request, queryset, InventoryFeatureSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = InventoryFeatureSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="INVENTORY_FEATURE_CREATED",
            message="Inventory feature created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class InventoryFeatureDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedPortfolioAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(InventoryFeature, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = InventoryFeatureSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Inventory feature retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = InventoryFeatureSerializer(instance, data=payload, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="INVENTORY_FEATURE_UPDATED",
            message="Inventory feature updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = get_object_or_404(InventoryFeature, pk=pk, tenant_id=tenant_id, is_archived=False)
        instance.archive()
        return success_response(
            request,
            code="INVENTORY_FEATURE_DELETED",
            message="Inventory feature deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
