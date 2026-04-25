from django.urls import path

from apps.platform.invoices.views import GenerateInvoiceAPIView
from apps.platform.jobcards.views import (
    JobCardDetailAPIView,
    JobCardListCreateAPIView,
    JobCardPdfAPIView,
    JobCardStatsAPIView,
)

urlpatterns = [
    path("", JobCardListCreateAPIView.as_view(), name="job-card-list-create"),
    path("stats/", JobCardStatsAPIView.as_view(), name="job-card-stats"),
    path("<uuid:pk>/", JobCardDetailAPIView.as_view(), name="job-card-detail"),
    path("<uuid:pk>/generate-pdf/", JobCardPdfAPIView.as_view(), name="job-card-generate-pdf"),
    path("<uuid:job_card_id>/generate-invoice/", GenerateInvoiceAPIView.as_view(), name="job-card-generate-invoice"),
]
