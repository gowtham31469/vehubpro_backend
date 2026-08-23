from django.urls import path
from apps.platform.users.views import (
    TenantAdminListCreateAPIView,
    TenantAdminDetailAPIView,
    StaffUserListCreateAPIView,
    StaffUserDetailAPIView,
)

urlpatterns = [
    path("tenant-admins/", TenantAdminListCreateAPIView.as_view(), name="tenant-admin-list-create"),
    path("tenant-admins/<uuid:pk>/", TenantAdminDetailAPIView.as_view(), name="tenant-admin-detail"),
    path("staff/", StaffUserListCreateAPIView.as_view(), name="staff-user-list-create"),
    path("staff/<uuid:pk>/", StaffUserDetailAPIView.as_view(), name="staff-user-detail"),
]
