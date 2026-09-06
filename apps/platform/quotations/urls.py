from django.urls import path

from apps.platform.quotations.views import (
    QuotationApproveAPIView,
    QuotationCancelAPIView,
    QuotationConvertToJobCardAPIView,
    QuotationDetailAPIView,
    QuotationListCreateAPIView,
    QuotationPdfAPIView,
    QuotationPreviewHtmlAPIView,
    QuotationRejectAPIView,
    QuotationReviseAPIView,
    QuotationRevisionsListAPIView,
    QuotationSendAPIView,
)

urlpatterns = [
    path("", QuotationListCreateAPIView.as_view(), name="quotation-list-create"),
    path("<uuid:pk>/", QuotationDetailAPIView.as_view(), name="quotation-detail"),
    path("<uuid:pk>/send/", QuotationSendAPIView.as_view(), name="quotation-send"),
    path("<uuid:pk>/approve/", QuotationApproveAPIView.as_view(), name="quotation-approve"),
    path("<uuid:pk>/reject/", QuotationRejectAPIView.as_view(), name="quotation-reject"),
    path("<uuid:pk>/cancel/", QuotationCancelAPIView.as_view(), name="quotation-cancel"),
    path("<uuid:pk>/revise/", QuotationReviseAPIView.as_view(), name="quotation-revise"),
    path("<uuid:pk>/revisions/", QuotationRevisionsListAPIView.as_view(), name="quotation-revisions"),
    path(
        "<uuid:pk>/convert-to-job-card/",
        QuotationConvertToJobCardAPIView.as_view(),
        name="quotation-convert-to-job-card",
    ),
    path("<uuid:pk>/preview-html/", QuotationPreviewHtmlAPIView.as_view(), name="quotation-preview-html"),
    path("<uuid:pk>/generate-pdf/", QuotationPdfAPIView.as_view(), name="quotation-generate-pdf"),
]
