from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.services.models import ServiceCategory, ServiceItem
from apps.platform.services.permissions import IsAuthenticatedServiceAccess
from apps.platform.services.serializers import (
    ServiceCategorySerializer,
    ServiceItemSerializer,
    _category_integrity_errors,
    _item_integrity_errors,
)
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _is_archive_flag(request):
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


def _is_active_flag(request):
    value = request.query_params.get("is_active")
    if value is None:
        return None
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


# ---------------------------------------------------------------------------
# Service Category
# ---------------------------------------------------------------------------


class ServiceCategoryListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedServiceAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = ServiceCategory.objects.filter(
            tenant_id=tenant_id, is_archived=_is_archive_flag(request)
        ).order_by("sort_order", "name")
        is_active = _is_active_flag(request)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service categories retrieved successfully.",
            data=build_paginated_data(request, queryset, ServiceCategorySerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = ServiceCategorySerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request,
                code="INTEGRITY_ERROR",
                message="Could not create service category.",
                error=_category_integrity_errors(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request,
            code="SERVICE_CATEGORY_CREATED",
            message="Service category created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class ServiceCategoryDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedServiceAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(ServiceCategory, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = ServiceCategorySerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service category retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = ServiceCategorySerializer(instance, data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request,
                code="INTEGRITY_ERROR",
                message="Could not update service category.",
                error=_category_integrity_errors(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request,
            code="SERVICE_CATEGORY_UPDATED",
            message="Service category updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = ServiceCategorySerializer(
            instance, data=payload, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request,
                code="INTEGRITY_ERROR",
                message="Could not update service category.",
                error=_category_integrity_errors(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request,
            code="SERVICE_CATEGORY_UPDATED",
            message="Service category updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        category = get_object_or_404(ServiceCategory, pk=pk, tenant_id=tenant_id, is_archived=False)
        now = timezone.now()
        ServiceItem.objects.filter(
            category_id=category.id, tenant_id=tenant_id, is_archived=False
        ).update(is_archived=True, archived_at=now, updated_at=now)
        category.archive()
        return success_response(
            request,
            code="SERVICE_CATEGORY_DELETED",
            message="Service category archived successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Service Item
# ---------------------------------------------------------------------------


class ServiceItemListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedServiceAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        category_id = request.query_params.get("category_id")
        queryset = (
            ServiceItem.objects.select_related("category", "tenant")
            .filter(tenant_id=tenant_id, is_archived=_is_archive_flag(request))
            .order_by("name")
        )
        if category_id:
            queryset = queryset.filter(category_id=category_id, category__tenant_id=tenant_id)
        is_active = _is_active_flag(request)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
            if is_active:
                queryset = queryset.filter(category__is_active=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service items retrieved successfully.",
            data=build_paginated_data(request, queryset, ServiceItemSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = ServiceItemSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request,
                code="INTEGRITY_ERROR",
                message="Could not create service item.",
                error=_item_integrity_errors(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request,
            code="SERVICE_ITEM_CREATED",
            message="Service item created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class ServiceItemDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedServiceAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(ServiceItem, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        serializer = ServiceItemSerializer(instance)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service item retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = ServiceItemSerializer(instance, data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request,
                code="INTEGRITY_ERROR",
                message="Could not update service item.",
                error=_item_integrity_errors(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request,
            code="SERVICE_ITEM_UPDATED",
            message="Service item updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = ServiceItemSerializer(
            instance, data=payload, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request,
                code="INTEGRITY_ERROR",
                message="Could not update service item.",
                error=_item_integrity_errors(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request,
            code="SERVICE_ITEM_UPDATED",
            message="Service item updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        item = get_object_or_404(ServiceItem, pk=pk, tenant_id=tenant_id, is_archived=False)
        item.archive()
        return success_response(
            request,
            code="SERVICE_ITEM_DELETED",
            message="Service item archived successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
