from django.urls import path

from apps.platform.portfolio.public_views import PublicInventoryVehiclesAPIView, PublicVehicleBrandsAPIView

urlpatterns = [
    path("tenants/<str:domain>/inventory/", PublicInventoryVehiclesAPIView.as_view(), name="public-inventory-vehicles"),
    path("tenants/<str:domain>/brands/", PublicVehicleBrandsAPIView.as_view(), name="public-vehicle-brands"),
]
