from rest_framework import status
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from apps.platform.users.models import User
from apps.platform.users.serializers import TenantAdminSerializer
from apps.platform.tenants.permissions import IsSuperAdminRole
from core.utils.api_response import success_response
from core.utils.pagination import build_paginated_data

class TenantAdminListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        tenant_id = request.query_params.get("tenant_id")
        queryset = User.objects.select_related("role", "tenant").prefetch_related("pii").filter(is_archived=False)
        
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
            
        # Only show ADMIN role users for tenant admin management
        queryset = queryset.filter(role__code="ADMIN")
        
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant admins retrieved successfully.",
            data=build_paginated_data(request, queryset, TenantAdminSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TenantAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="USER_CREATED",
            message="Tenant admin created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )

class TenantAdminDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, pk):
        return get_object_or_404(User, pk=pk, is_archived=False)

    def get(self, request, pk):
        user = self.get_object(pk)
        serializer = TenantAdminSerializer(user)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="User retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        user = self.get_object(pk)
        serializer = TenantAdminSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="USER_UPDATED",
            message="User updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        user = self.get_object(pk)
        user.archive()
        return success_response(
            request,
            code="USER_DELETED",
            message="User deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
