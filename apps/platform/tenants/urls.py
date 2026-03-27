from django.urls import path

from apps.platform.tenants.views import (
    TenantBrandingByTokenAPIView,
    TenantBrandingDetailAPIView,
    TenantBrandingListCreateAPIView,
    TenantDetailAPIView,
    TenantListCreateAPIView,
    TenantPIIDetailAPIView,
    TenantPIIListCreateAPIView,
)

urlpatterns = [
    path("", TenantListCreateAPIView.as_view(), name="tenant-list-create"),
    path("<uuid:pk>/", TenantDetailAPIView.as_view(), name="tenant-detail"),
    path("branding/", TenantBrandingListCreateAPIView.as_view(), name="tenant-branding-list-create"),
    path("branding/me/", TenantBrandingByTokenAPIView.as_view(), name="tenant-branding-by-token"),
    path("branding/<uuid:pk>/", TenantBrandingDetailAPIView.as_view(), name="tenant-branding-detail"),
    path("pii/", TenantPIIListCreateAPIView.as_view(), name="tenant-pii-list-create"),
    path("pii/<uuid:pk>/", TenantPIIDetailAPIView.as_view(), name="tenant-pii-detail"),
]
