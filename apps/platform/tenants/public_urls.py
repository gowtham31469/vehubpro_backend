from django.urls import path

from apps.platform.tenants.views import PublicTenantBrandingAPIView

urlpatterns = [
    path("tenants/<str:domain>/branding/", PublicTenantBrandingAPIView.as_view(), name="public-tenant-branding"),
]
