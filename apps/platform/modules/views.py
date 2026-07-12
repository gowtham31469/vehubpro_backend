from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from rest_framework.permissions import IsAuthenticated

from apps.platform.modules.models import Module, Submodule, Permission, TenantModule
from apps.platform.modules.permissions import IsSuperAdminRole
from apps.platform.modules.serializers import (
    ModuleSerializer,
    ModuleDetailSerializer,
    NavModuleSerializer,
    SubmoduleSerializer,
    PermissionSerializer,
    TenantModuleSerializer,
)
from core.utils.api_response import success_response
from core.utils.pagination import build_paginated_data


class ModuleListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = Module.objects.filter(is_archived=False).order_by("name")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Modules retrieved successfully.",
            data=build_paginated_data(request, queryset, ModuleSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = ModuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return success_response(
            request,
            code="MODULE_CREATED",
            message="Module created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class ModuleDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, pk):
        return get_object_or_404(Module, pk=pk, is_archived=False)

    def get(self, request, pk):
        serializer = ModuleDetailSerializer(self.get_object(pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Module retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        module = self.get_object(pk)
        serializer = ModuleSerializer(module, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="MODULE_UPDATED",
            message="Module updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        self.get_object(pk).archive()
        return success_response(
            request,
            code="MODULE_DELETED",
            message="Module archived successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class SubmoduleListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_module(self, module_pk):
        return get_object_or_404(Module, pk=module_pk, is_archived=False)

    def get(self, request, module_pk):
        module = self.get_module(module_pk)
        queryset = module.submodules.filter(is_archived=False).order_by("name")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Submodules retrieved successfully.",
            data=build_paginated_data(request, queryset, SubmoduleSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, module_pk):
        module = self.get_module(module_pk)
        serializer = SubmoduleSerializer(data={**request.data, "module": str(module.id)})
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return success_response(
            request,
            code="SUBMODULE_CREATED",
            message="Submodule created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class SubmoduleDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, module_pk, pk):
        return get_object_or_404(Submodule, pk=pk, module_id=module_pk, is_archived=False)

    def patch(self, request, module_pk, pk):
        sub = self.get_object(module_pk, pk)
        serializer = SubmoduleSerializer(sub, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="SUBMODULE_UPDATED",
            message="Submodule updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, module_pk, pk):
        self.get_object(module_pk, pk).archive()
        return success_response(
            request,
            code="SUBMODULE_DELETED",
            message="Submodule archived successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class PermissionListAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = Permission.objects.all().order_by("name")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Permissions retrieved successfully.",
            data=build_paginated_data(request, queryset, PermissionSerializer),
            status_code=status.HTTP_200_OK,
        )


class TenantModuleDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, pk):
        return get_object_or_404(TenantModule, pk=pk)

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return success_response(
            request,
            code="TENANT_MODULE_REMOVED",
            message="Tenant module assignment removed.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class TenantModuleListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        tenant_id = request.query_params.get("tenant_id")
        queryset = TenantModule.objects.select_related("module", "tenant")
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        queryset = queryset.order_by("priority", "created_at")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant modules retrieved successfully.",
            data=build_paginated_data(request, queryset, TenantModuleSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TenantModuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return success_response(
            request,
            code="TENANT_MODULE_CREATED",
            message="Tenant module assigned successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )

class UserModuleNavAPIView(APIView):
    """
    Returns the modules (and their submodules) assigned to the authenticated user's
    tenant, ordered by priority. Used by the frontend to build the sidebar nav dynamically.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = getattr(request.user, "tenant_id", None)
        if not tenant_id:
            return success_response(
                request,
                code="TENANT_CONTEXT_MISSING",
                message="User is not mapped to a tenant.",
                data=[],
                status_code=status.HTTP_200_OK,
            )

        module_ids = (
            TenantModule.objects.filter(tenant_id=tenant_id)
            .values_list("module_id", flat=True)
        )

        modules = Module.objects.filter(
            id__in=list(module_ids),
            is_archived=False,
            is_active=True,
        ).prefetch_related("submodules").order_by("id")

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="User nav modules retrieved.",
            data=NavModuleSerializer(modules, many=True).data,
            status_code=status.HTTP_200_OK,
        )


class TenantModulePermissionsAPIView(APIView):
    """
    Returns the hierarchy of Modules -> Submodules -> SubmodulePermissions
    assigned to a specific tenant. Used for granular permission assignment.
    """
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        tenant_id = request.query_params.get("tenant_id")
        if not tenant_id:
            return success_response(
                request,
                code="MISSING_TENANT_ID",
                message="tenant_id query parameter is required.",
                data=[],
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # 1. Get modules assigned to this tenant
        assigned_module_ids = TenantModule.objects.filter(
            tenant_id=tenant_id
        ).values_list("module_id", flat=True)

        if not assigned_module_ids:
            return success_response(
                request,
                code="DATA_RETRIEVED",
                message="No modules assigned to this tenant.",
                data=[],
                status_code=status.HTTP_200_OK
            )

        # 2. Fetch full hierarchy for these modules
        queryset = Module.objects.filter(
            id__in=assigned_module_ids,
            is_archived=False
        ).prefetch_related(
            "submodules",
            "submodules__permissions",
            "submodules__permissions__permission"
        ).order_by("name")

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant permission hierarchy retrieved.",
            data=ModuleDetailSerializer(queryset, many=True).data,
            status_code=status.HTTP_200_OK,
        )
