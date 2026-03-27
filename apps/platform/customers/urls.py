from django.urls import path

from apps.platform.customers.views import CustomerDetailAPIView, CustomerListCreateAPIView

urlpatterns = [
    path("", CustomerListCreateAPIView.as_view(), name="customer-list-create"),
    path("<uuid:pk>/", CustomerDetailAPIView.as_view(), name="customer-detail"),
]
