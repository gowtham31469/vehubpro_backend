from django.urls import path

from apps.platform.services.public_views import PublicServiceCategoriesAPIView, PublicServiceItemsAPIView

urlpatterns = [
    path("tenants/<str:domain>/categories/", PublicServiceCategoriesAPIView.as_view(), name="public-service-categories"),
    path("tenants/<str:domain>/items/", PublicServiceItemsAPIView.as_view(), name="public-service-items"),
]
