from django.urls import path

from apps.platform.tenants.views import (
    TenantBrandingByTokenAPIView,
    TenantBrandingDetailAPIView,
    TenantBrandingListCreateAPIView,
    TenantDetailAPIView,
    TenantInvoiceSettingsByTokenAPIView,
    TenantInvoiceSettingsDetailAPIView,
    TenantInvoiceSettingsListCreateAPIView,
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
    path("invoice-settings/", TenantInvoiceSettingsListCreateAPIView.as_view(), name="tenant-invoice-settings-list-create"),
    path("invoice-settings/me/", TenantInvoiceSettingsByTokenAPIView.as_view(), name="tenant-invoice-settings-by-token"),
    path("invoice-settings/<uuid:pk>/", TenantInvoiceSettingsDetailAPIView.as_view(), name="tenant-invoice-settings-detail"),
]
