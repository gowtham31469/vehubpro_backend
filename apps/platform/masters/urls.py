from django.urls import path

from apps.platform.masters.views import CityListAPIView, RoleListAPIView, StateListAPIView

urlpatterns = [
    path("states/", StateListAPIView.as_view(), name="masters-state-list"),
    path("cities/", CityListAPIView.as_view(), name="masters-city-list"),
    path("roles/", RoleListAPIView.as_view(), name="masters-role-list"),
]
