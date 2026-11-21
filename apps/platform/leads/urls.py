from django.urls import path

from apps.platform.leads.views import (
    LeadConvertAPIView,
    LeadConvertToInventoryAPIView,
    LeadDetailAPIView,
    LeadEventListAPIView,
    LeadListAPIView,
)

urlpatterns = [
    path("leads/", LeadListAPIView.as_view(), name="lead-list-create"),
    path("leads/<uuid:pk>/", LeadDetailAPIView.as_view(), name="lead-detail"),
    path("leads/<uuid:pk>/events/", LeadEventListAPIView.as_view(), name="lead-events"),
    path("leads/<uuid:pk>/convert/", LeadConvertAPIView.as_view(), name="lead-convert"),
    path(
        "leads/<uuid:pk>/convert-to-inventory/",
        LeadConvertToInventoryAPIView.as_view(),
        name="lead-convert-to-inventory",
    ),
]
