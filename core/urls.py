"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.urls import include, path, re_path
from django.views.static import serve


def serve_spa_or_health(request, *args, **kwargs):
    """
    Serve the superadmin SPA's index.html when it's been built and deployed
    alongside this backend. On API-only deployments (no superadmin/dist
    present) this falls back to a plain health response instead of 500ing.
    """
    try:
        return render(request, "index.html")
    except TemplateDoesNotExist:
        return JsonResponse({"status": "ok", "service": "vehubpro-api"})


# Media files must come before the SPA catch-all to avoid TemplateDoesNotExist
urlpatterns = static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("core.auth.urls")),
    path("api/v1/public/", include("apps.platform.tenants.public_urls")),
    path("api/v1/billing/", include("apps.platform.billing.urls")),
    path("api/v1/tenants/", include("apps.platform.tenants.urls")),
    path("api/v1/users/", include("apps.platform.users.urls")),
    path("api/v1/masters/", include("apps.platform.masters.urls")),
    path("api/v1/customers/", include("apps.platform.customers.urls")),
    path("api/v1/vehicles/", include("apps.platform.vehicles.urls")),
    path("api/v1/services/", include("apps.platform.services.urls")),
    path("api/v1/job-cards/", include("apps.platform.jobcards.urls")),
    path("api/v1/invoices/", include("apps.platform.invoices.urls")),
    path("api/v1/dashboard/", include("apps.platform.dashboard.urls")),
    path("api/v1/modules/", include("apps.platform.modules.urls")),
    # Superadmin SPA static assets (Vite build output)
    re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": settings.SUPERADMIN_DIST / "assets"}),
    # Catch-all: serve superadmin index.html for all non-API, non-admin, non-media routes
    # (falls back to a plain health response if the SPA hasn't been built/deployed here)
    re_path(r"^(?!api/|admin/|media/).*$", serve_spa_or_health),
]
