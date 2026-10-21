from django.urls import path

from apps.platform.proforma_invoices.views import (
    AdvancePaymentListCreateAPIView,
    AdvancePaymentMarkReceivedAPIView,
    AdvancePaymentRefundAPIView,
    AdvancePaymentReverseAPIView,
    AdvanceReceiptPdfAPIView,
    AdvanceReceiptPreviewHtmlAPIView,
    ProformaInvoiceApproveAPIView,
    ProformaInvoiceCancelAPIView,
    ProformaInvoiceConvertAPIView,
    ProformaInvoiceDetailAPIView,
    ProformaInvoiceIssueAPIView,
    ProformaInvoiceListAPIView,
    ProformaInvoicePdfAPIView,
    ProformaInvoicePreviewHtmlAPIView,
    ProformaInvoiceRejectAPIView,
    ProformaInvoiceReviseAPIView,
    ProformaInvoiceRevisionsAPIView,
)

urlpatterns = [
    path("", ProformaInvoiceListAPIView.as_view(), name="proforma-invoice-list"),
    path("<uuid:pk>/", ProformaInvoiceDetailAPIView.as_view(), name="proforma-invoice-detail"),
    path("<uuid:pk>/issue/", ProformaInvoiceIssueAPIView.as_view(), name="proforma-invoice-issue"),
    path("<uuid:pk>/approve/", ProformaInvoiceApproveAPIView.as_view(), name="proforma-invoice-approve"),
    path("<uuid:pk>/reject/", ProformaInvoiceRejectAPIView.as_view(), name="proforma-invoice-reject"),
    path("<uuid:pk>/cancel/", ProformaInvoiceCancelAPIView.as_view(), name="proforma-invoice-cancel"),
    path("<uuid:pk>/revise/", ProformaInvoiceReviseAPIView.as_view(), name="proforma-invoice-revise"),
    path("<uuid:pk>/revisions/", ProformaInvoiceRevisionsAPIView.as_view(), name="proforma-invoice-revisions"),
    path("<uuid:pk>/convert/", ProformaInvoiceConvertAPIView.as_view(), name="proforma-invoice-convert"),
    path("<uuid:pk>/preview-html/", ProformaInvoicePreviewHtmlAPIView.as_view(), name="proforma-invoice-preview-html"),
    path("<uuid:pk>/generate-pdf/", ProformaInvoicePdfAPIView.as_view(), name="proforma-invoice-generate-pdf"),
    path("<uuid:pk>/advance-payments/", AdvancePaymentListCreateAPIView.as_view(), name="proforma-invoice-advance-payments"),
]

# Mounted separately at /api/v1/advance-payments/ in core/urls.py — these act
# on an AdvancePayment directly (not nested under a specific proforma), same
# split as invoices/{id}/record-payment/ vs job-cards/{id}/generate-invoice/.
advance_payment_urlpatterns = [
    path("<uuid:pk>/mark-received/", AdvancePaymentMarkReceivedAPIView.as_view(), name="advance-payment-mark-received"),
    path("<uuid:pk>/reverse/", AdvancePaymentReverseAPIView.as_view(), name="advance-payment-reverse"),
    path("<uuid:pk>/refund/", AdvancePaymentRefundAPIView.as_view(), name="advance-payment-refund"),
    path("<uuid:pk>/receipt/preview-html/", AdvanceReceiptPreviewHtmlAPIView.as_view(), name="advance-receipt-preview-html"),
    path("<uuid:pk>/receipt/generate-pdf/", AdvanceReceiptPdfAPIView.as_view(), name="advance-receipt-generate-pdf"),
]
