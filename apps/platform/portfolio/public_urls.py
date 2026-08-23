from django.urls import path

from apps.platform.portfolio.public_views import PublicInventoryVehiclesAPIView

urlpatterns = [
    path("tenants/<str:domain>/inventory/", PublicInventoryVehiclesAPIView.as_view(), name="public-inventory-vehicles"),
]
