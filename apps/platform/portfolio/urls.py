from django.urls import path

from apps.platform.portfolio.views import (
    InventoryFeatureDetailAPIView,
    InventoryFeatureListCreateAPIView,
    InventoryVehicleDetailAPIView,
    InventoryVehicleListCreateAPIView,
    PortfolioDashboardSummaryView,
    VisitRequestDetailAPIView,
    VisitRequestEventListAPIView,
    VisitRequestListAPIView,
)

urlpatterns = [
    path("inventory-vehicles/", InventoryVehicleListCreateAPIView.as_view(), name="inventory-vehicle-list-create"),
    path("inventory-vehicles/<uuid:pk>/", InventoryVehicleDetailAPIView.as_view(), name="inventory-vehicle-detail"),
    path("inventory-features/", InventoryFeatureListCreateAPIView.as_view(), name="inventory-feature-list-create"),
    path("inventory-features/<uuid:pk>/", InventoryFeatureDetailAPIView.as_view(), name="inventory-feature-detail"),
    path("dashboard-summary/", PortfolioDashboardSummaryView.as_view(), name="portfolio-dashboard-summary"),
    path("visit-requests/", VisitRequestListAPIView.as_view(), name="visit-request-list"),
    path("visit-requests/<uuid:pk>/", VisitRequestDetailAPIView.as_view(), name="visit-request-detail"),
    path("visit-requests/<uuid:pk>/events/", VisitRequestEventListAPIView.as_view(), name="visit-request-events"),
]
