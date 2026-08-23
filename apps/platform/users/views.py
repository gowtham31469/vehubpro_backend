from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from apps.platform.users.models import User
from apps.platform.users.serializers import TenantAdminSerializer, StaffUserSerializer
from apps.platform.tenants.permissions import IsSuperAdminRole
from core.utils.api_response import error_response, success_response
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


class StaffUserListCreateAPIView(APIView):
    """
    Tenant portal's User Management module — CRUD for staff users, scoped to
    the authenticated user's own tenant. SUPER_ADMIN accounts are never
    listed/manageable here, even if one happens to carry this tenant_id.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = (
            User.objects.select_related("role")
            .prefetch_related("pii")
            .filter(tenant_id=tenant_id, is_archived=False)
            .exclude(role__code="SUPER_ADMIN")
            .order_by("-created_at")
        )
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Staff users retrieved successfully.",
            data=build_paginated_data(request, queryset, StaffUserSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        serializer = StaffUserSerializer(data=request.data, context={"tenant_id": tenant_id})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="USER_CREATED",
            message="Staff user created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class StaffUserDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        queryset = (
            User.objects.select_related("role")
            .prefetch_related("pii")
            .filter(tenant_id=tenant_id, is_archived=False)
            .exclude(role__code="SUPER_ADMIN")
        )
        return get_object_or_404(queryset, pk=pk)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = StaffUserSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Staff user retrieved successfully.",
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
        serializer = StaffUserSerializer(
            instance, data=request.data, partial=partial, context={"tenant_id": tenant_id}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="USER_UPDATED",
            message="Staff user updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        if str(request.user.id) == str(pk):
            return error_response(
                request,
                code="CANNOT_ARCHIVE_SELF",
                message="You cannot archive your own account.",
                error="Self-archival is not allowed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        instance = self.get_object(request, pk)
        instance.archive()
        return success_response(
            request,
            code="USER_DELETED",
            message="Staff user archived successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
