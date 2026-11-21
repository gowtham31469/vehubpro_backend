from django.urls import path

from apps.platform.leads.public_views import PublicLeadCreateAPIView, PublicVehicleEnquiryCreateAPIView

urlpatterns = [
    path("tenants/<str:domain>/enquire/", PublicLeadCreateAPIView.as_view(), name="public-lead-enquire"),
    path(
        "tenants/<str:domain>/vehicles/<uuid:pk>/enquire/",
        PublicVehicleEnquiryCreateAPIView.as_view(),
        name="public-vehicle-enquire",
    ),
]
