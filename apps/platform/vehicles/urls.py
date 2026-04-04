from django.urls import path

from apps.platform.vehicles.views import (
    FuelTypeDetailAPIView,
    FuelTypeListCreateAPIView,
    ServiceVehicleDetailAPIView,
    ServiceVehicleListCreateAPIView,
    VehicleBrandDetailAPIView,
    VehicleBrandListCreateAPIView,
    VehicleModelDetailAPIView,
    VehicleModelListCreateAPIView,
    VehicleTypeDetailAPIView,
    VehicleTypeListCreateAPIView,
)

urlpatterns = [
    path("types/", VehicleTypeListCreateAPIView.as_view(), name="vehicle-type-list-create"),
    path("types/<uuid:pk>/", VehicleTypeDetailAPIView.as_view(), name="vehicle-type-detail"),
    path("fuel-types/", FuelTypeListCreateAPIView.as_view(), name="fuel-type-list-create"),
    path("fuel-types/<uuid:pk>/", FuelTypeDetailAPIView.as_view(), name="fuel-type-detail"),
    path("brands/", VehicleBrandListCreateAPIView.as_view(), name="vehicle-brand-list-create"),
    path("brands/<uuid:pk>/", VehicleBrandDetailAPIView.as_view(), name="vehicle-brand-detail"),
    path("models/", VehicleModelListCreateAPIView.as_view(), name="vehicle-model-list-create"),
    path("models/<uuid:pk>/", VehicleModelDetailAPIView.as_view(), name="vehicle-model-detail"),
    path("", ServiceVehicleListCreateAPIView.as_view(), name="vehicle-list-create"),
    path("<uuid:pk>/", ServiceVehicleDetailAPIView.as_view(), name="vehicle-detail"),
]
