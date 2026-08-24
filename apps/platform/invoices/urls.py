from django.urls import path

from apps.platform.invoices.views import (
    InvoiceCancelAPIView,
    InvoiceDetailAPIView,
    InvoiceListAPIView,
    InvoicePdfAPIView,
    InvoicePreviewHtmlAPIView,
    RecordPaymentAPIView,
)

urlpatterns = [
    path("", InvoiceListAPIView.as_view(), name="invoice-list"),
    path("<uuid:pk>/", InvoiceDetailAPIView.as_view(), name="invoice-detail"),
    path("<uuid:pk>/preview-html/", InvoicePreviewHtmlAPIView.as_view(), name="invoice-preview-html"),
    path("<uuid:pk>/record-payment/", RecordPaymentAPIView.as_view(), name="invoice-record-payment"),
    path("<uuid:pk>/generate-pdf/", InvoicePdfAPIView.as_view(), name="invoice-generate-pdf"),
    path("<uuid:pk>/cancel/", InvoiceCancelAPIView.as_view(), name="invoice-cancel"),
]
