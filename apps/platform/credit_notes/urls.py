from django.urls import path

from apps.platform.credit_notes.views import (
    CreditNoteCancelAPIView,
    CreditNoteDetailAPIView,
    CreditNoteListAPIView,
    CreditNoteMarkRefundedAPIView,
    CreditNotePdfAPIView,
    CreditNotePreviewHtmlAPIView,
    CreditNoteReasonCategoryDetailAPIView,
    CreditNoteReasonCategoryListCreateAPIView,
)

urlpatterns = [
    path("reason-categories/", CreditNoteReasonCategoryListCreateAPIView.as_view(), name="credit-note-reason-category-list-create"),
    path("reason-categories/<uuid:pk>/", CreditNoteReasonCategoryDetailAPIView.as_view(), name="credit-note-reason-category-detail"),
    path("", CreditNoteListAPIView.as_view(), name="credit-note-list"),
    path("<uuid:pk>/", CreditNoteDetailAPIView.as_view(), name="credit-note-detail"),
    path("<uuid:pk>/preview-html/", CreditNotePreviewHtmlAPIView.as_view(), name="credit-note-preview-html"),
    path("<uuid:pk>/generate-pdf/", CreditNotePdfAPIView.as_view(), name="credit-note-generate-pdf"),
    path("<uuid:pk>/mark-refunded/", CreditNoteMarkRefundedAPIView.as_view(), name="credit-note-mark-refunded"),
    path("<uuid:pk>/cancel/", CreditNoteCancelAPIView.as_view(), name="credit-note-cancel"),
]
