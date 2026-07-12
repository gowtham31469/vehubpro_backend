from django.urls import path
from apps.platform.users.views import TenantAdminListCreateAPIView, TenantAdminDetailAPIView

urlpatterns = [
    path("tenant-admins/", TenantAdminListCreateAPIView.as_view(), name="tenant-admin-list-create"),
    path("tenant-admins/<uuid:pk>/", TenantAdminDetailAPIView.as_view(), name="tenant-admin-detail"),
]
