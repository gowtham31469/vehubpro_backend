from django.urls import path

from apps.platform.invoices.views import (
    InvoiceDetailAPIView,
    InvoiceListAPIView,
    InvoicePdfAPIView,
    RecordPaymentAPIView,
)

urlpatterns = [
    path("", InvoiceListAPIView.as_view(), name="invoice-list"),
    path("<uuid:pk>/", InvoiceDetailAPIView.as_view(), name="invoice-detail"),
    path("<uuid:pk>/record-payment/", RecordPaymentAPIView.as_view(), name="invoice-record-payment"),
    path("<uuid:pk>/generate-pdf/", InvoicePdfAPIView.as_view(), name="invoice-generate-pdf"),
]
