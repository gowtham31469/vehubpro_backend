from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.platform.customers.models import Customer
from apps.platform.customers.permissions import IsAuthenticatedCustomerAccess
from apps.platform.customers.serializers import CustomerSerializer
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _is_archive_flag(request):
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


class CustomerListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedCustomerAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _tenant_context(self, request):
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

    def get(self, request):
        tenant_id, error = self._tenant_context(request)
        if error:
            return error
        queryset = Customer.objects.select_related("tenant", "state", "city").filter(
            tenant_id=tenant_id,
            is_archived=_is_archive_flag(request),
        ).order_by("-created_at")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Customers retrieved successfully.",
            data=build_paginated_data(request, queryset, CustomerSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = self._tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)

        serializer = CustomerSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="CUSTOMER_CREATED",
            message="Customer created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class CustomerDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedCustomerAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _tenant_context(self, request):
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

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        queryset = Customer.objects.select_related("tenant", "state", "city").filter(
            pk=pk,
            is_archived=_is_archive_flag(request),
        )
        return get_object_or_404(queryset, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = self._tenant_context(request)
        if error:
            return error
        serializer = CustomerSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Customer retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = self._tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = CustomerSerializer(instance, data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="CUSTOMER_UPDATED",
            message="Customer updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = self._tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = CustomerSerializer(instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="CUSTOMER_UPDATED",
            message="Customer updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        _, error = self._tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        instance.archive()
        return success_response(
            request,
            code="CUSTOMER_DELETED",
            message="Customer deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
