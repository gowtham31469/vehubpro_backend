from django.urls import path

from apps.platform.vendors.views import (
    VendorBillCancelAPIView,
    VendorBillDetailAPIView,
    VendorBillListCreateAPIView,
    VendorCategoryDetailAPIView,
    VendorCategoryListCreateAPIView,
    VendorDetailAPIView,
    VendorInsightsAPIView,
    VendorListCreateAPIView,
    VendorPaymentListCreateAPIView,
    VendorPaymentVoidAPIView,
)

urlpatterns = [
    path("insights/", VendorInsightsAPIView.as_view(), name="vendor-insights"),
    path("categories/", VendorCategoryListCreateAPIView.as_view(), name="vendor-category-list-create"),
    path("categories/<uuid:pk>/", VendorCategoryDetailAPIView.as_view(), name="vendor-category-detail"),
    path("bills/", VendorBillListCreateAPIView.as_view(), name="vendor-bill-list-create"),
    path("bills/<uuid:pk>/", VendorBillDetailAPIView.as_view(), name="vendor-bill-detail"),
    path("bills/<uuid:pk>/cancel/", VendorBillCancelAPIView.as_view(), name="vendor-bill-cancel"),
    path("payments/", VendorPaymentListCreateAPIView.as_view(), name="vendor-payment-list-create"),
    path("payments/<uuid:pk>/void/", VendorPaymentVoidAPIView.as_view(), name="vendor-payment-void"),
    path("", VendorListCreateAPIView.as_view(), name="vendor-list-create"),
    path("<uuid:pk>/", VendorDetailAPIView.as_view(), name="vendor-detail"),
]
