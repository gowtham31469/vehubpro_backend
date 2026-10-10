from django.urls import path

from apps.platform.services.views import (
    ServiceCategoryDetailAPIView,
    ServiceCategoryImageAPIView,
    ServiceCategoryListCreateAPIView,
    ServiceItemDetailAPIView,
    ServiceItemImageAPIView,
    ServiceItemListCreateAPIView,
)

urlpatterns = [
    path("categories/", ServiceCategoryListCreateAPIView.as_view(), name="service-category-list-create"),
    path("categories/<uuid:pk>/", ServiceCategoryDetailAPIView.as_view(), name="service-category-detail"),
    path("categories/<uuid:pk>/image/", ServiceCategoryImageAPIView.as_view(), name="service-category-image"),
    path("items/", ServiceItemListCreateAPIView.as_view(), name="service-item-list-create"),
    path("items/<uuid:pk>/", ServiceItemDetailAPIView.as_view(), name="service-item-detail"),
    path("items/<uuid:pk>/image/", ServiceItemImageAPIView.as_view(), name="service-item-image"),
]
