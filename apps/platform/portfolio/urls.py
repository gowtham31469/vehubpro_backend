from django.urls import path

from apps.platform.portfolio.views import (
    InventoryFeatureDetailAPIView,
    InventoryFeatureListCreateAPIView,
    InventoryVehicleDetailAPIView,
    InventoryVehicleListCreateAPIView,
)

urlpatterns = [
    path("inventory-vehicles/", InventoryVehicleListCreateAPIView.as_view(), name="inventory-vehicle-list-create"),
    path("inventory-vehicles/<uuid:pk>/", InventoryVehicleDetailAPIView.as_view(), name="inventory-vehicle-detail"),
    path("inventory-features/", InventoryFeatureListCreateAPIView.as_view(), name="inventory-feature-list-create"),
    path("inventory-features/<uuid:pk>/", InventoryFeatureDetailAPIView.as_view(), name="inventory-feature-detail"),
]
