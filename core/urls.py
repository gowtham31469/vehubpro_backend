"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("core.auth.urls")),
    path("api/v1/billing/", include("apps.platform.billing.urls")),
    path("api/v1/tenants/", include("apps.platform.tenants.urls")),
    path("api/v1/masters/", include("apps.platform.masters.urls")),
    path("api/v1/customers/", include("apps.platform.customers.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
