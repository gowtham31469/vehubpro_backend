from django.urls import path
from apps.platform.modules.views import (
    ModuleListCreateAPIView,
    ModuleDetailAPIView,
    SubmoduleListCreateAPIView,
    SubmoduleDetailAPIView,
    PermissionListAPIView,
    TenantModuleListCreateAPIView,
    TenantModuleDetailAPIView,
    TenantModulePermissionsAPIView,
    TenantPortalModulePermissionsAPIView,
    UserModuleNavAPIView,
)

urlpatterns = [
    path("", ModuleListCreateAPIView.as_view(), name="module-list-create"),
    path("me/", UserModuleNavAPIView.as_view(), name="user-module-nav"),
    path("permissions/", PermissionListAPIView.as_view(), name="permission-list"),
    path("tenant-permissions/", TenantModulePermissionsAPIView.as_view(), name="tenant-permission-list"),
    path(
        "my-tenant-permissions/",
        TenantPortalModulePermissionsAPIView.as_view(),
        name="tenant-portal-permission-list",
    ),
    path("assignments/", TenantModuleListCreateAPIView.as_view(), name="tenant-module-list-create"),
    path("assignments/<uuid:pk>/", TenantModuleDetailAPIView.as_view(), name="tenant-module-detail"),
    path("<uuid:pk>/", ModuleDetailAPIView.as_view(), name="module-detail"),
    path("<uuid:module_pk>/submodules/", SubmoduleListCreateAPIView.as_view(), name="submodule-list-create"),
    path("<uuid:module_pk>/submodules/<uuid:pk>/", SubmoduleDetailAPIView.as_view(), name="submodule-detail"),
]
