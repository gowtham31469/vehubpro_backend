"""
Credit Note views.

Endpoints
---------
POST  /api/v1/invoices/{invoice_id}/credit-notes/   Issue a credit note against an invoice.
GET   /api/v1/credit-notes/                         List all credit notes for the tenant.
GET   /api/v1/credit-notes/{id}/                    Full credit note detail.
GET   /api/v1/credit-notes/{id}/preview-html/        Raw HTML for the PDF preview iframe.
POST  /api/v1/credit-notes/{id}/generate-pdf/        Generate (or return cached) PDF.
PATCH /api/v1/credit-notes/{id}/mark-refunded/       Mark a pending refund as refunded.
PATCH /api/v1/credit-notes/{id}/cancel/              Void a credit note.

All views enforce tenant isolation: only credit notes belonging to
request.user.tenant_id are ever returned or mutated.
"""
from __future__ import annotations

from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.credit_notes.models import CreditNote, CreditNoteReasonCategory
from apps.platform.credit_notes.permissions import IsAuthenticatedCreditNoteAccess
from apps.platform.credit_notes.serializers import (
    CancelCreditNoteSerializer,
    CreditNoteDetailSerializer,
    CreditNoteListSerializer,
    CreditNoteReasonCategorySerializer,
    GenerateCreditNoteSerializer,
    MarkRefundedSerializer,
    reason_category_integrity_errors,
)
from apps.platform.credit_notes.service import (
    CreditNoteAlreadyCancelled,
    CreditNoteAlreadyRefunded,
    CreditNoteService,
    InvalidCreditNoteRefundState,
    InvalidLineItemReference,
    InvoiceIsCancelled,
    NoCreditTargetSpecified,
    OverCreditError,
)
from apps.platform.credit_notes.pdf_service import (
    CreditNotePdfService,
    PdfGenerationError,
    PdfNotAvailableError,
)
from apps.platform.invoices.models import Invoice
from apps.platform.invoices.permissions import IsAuthenticatedInvoiceAccess
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _tenant_context(request):
    tenant_id = getattr(request.user, "tenant_id", None)
    if not tenant_id:
        return None, error_response(
            request,
            code="TENANT_CONTEXT_MISSING",
            message="Authenticated user is not mapped to a tenant.",
            error="Tenant association is required for this endpoint.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return tenant_id, None


def _bool_param(request, name: str) -> bool:
    return request.query_params.get(name, "false").strip().lower() in {"true", "1", "yes"}


# ── Generate credit note from an invoice ─────────────────────────────────────

class GenerateCreditNoteAPIView(APIView):
    """
    POST /api/v1/invoices/{invoice_id}/credit-notes/

    Issues a credit note (full or partial) against an invoice. Mounted under
    invoices' own URL file, mirroring how generate-invoice is mounted under
    job-cards relative to its source document.
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def post(self, request, invoice_id):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = get_object_or_404(
            Invoice.objects.prefetch_related("line_items"),
            pk=invoice_id,
            tenant_id=tenant_id,
        )

        serializer = GenerateCreditNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        try:
            credit_note = CreditNoteService.generate(
                invoice,
                created_by=request.user,
                line_item_credits=vd.get("line_item_credits"),
                custom_amount=vd.get("custom_amount"),
                custom_gst_percentage=vd.get("custom_gst_percentage"),
                reason=vd["reason"],
                reason_category=vd.get("reason_category", ""),
            )
        except InvoiceIsCancelled as exc:
            return error_response(
                request, code="INVOICE_IS_CANCELLED", message=str(exc),
                error="A cancelled invoice cannot be credited.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        except NoCreditTargetSpecified as exc:
            return error_response(
                request, code="NO_CREDIT_TARGET", message=str(exc),
                error="Specify at least one line item credit or a custom amount.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidLineItemReference as exc:
            return error_response(
                request, code="INVALID_LINE_ITEM", message=str(exc),
                error="One of the referenced line items does not belong to this invoice.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except OverCreditError as exc:
            return error_response(
                request, code="OVER_CREDIT", message=str(exc),
                error="The requested credit exceeds what's left creditable on this invoice.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_credit_note_event(request, credit_note, "CREDIT_NOTE_ISSUED")

        credit_note = CreditNote.objects.prefetch_related("line_items").select_related("invoice").get(
            pk=credit_note.pk
        )
        return success_response(
            request,
            code="CREDIT_NOTE_ISSUED",
            message=f"Credit note {credit_note.credit_note_number} issued successfully.",
            data=CreditNoteDetailSerializer(credit_note).data,
            status_code=status.HTTP_201_CREATED,
        )


# ── List ──────────────────────────────────────────────────────────────────────

class CreditNoteListAPIView(APIView):
    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = CreditNote.objects.filter(tenant_id=tenant_id).select_related("invoice", "issued_by")

        status_filter = request.query_params.get("status", "").strip()
        if status_filter in {CreditNote.STATUS_ISSUED, CreditNote.STATUS_CANCELLED}:
            queryset = queryset.filter(status=status_filter)

        refund_status = request.query_params.get("refund_status", "").strip()
        if refund_status in dict(CreditNote.REFUND_STATUS_CHOICES):
            queryset = queryset.filter(refund_status=refund_status)

        invoice_id = request.query_params.get("invoice_id", "").strip()
        if invoice_id:
            queryset = queryset.filter(invoice_id=invoice_id)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(credit_note_number__icontains=search) | Q(invoice__invoice_number__icontains=search)
            )

        date_from = request.query_params.get("date_from", "").strip()
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get("date_to", "").strip()
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        queryset = queryset.order_by("-created_at", "-credit_note_number")

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Credit notes retrieved successfully.",
            data=build_paginated_data(request, queryset, CreditNoteListSerializer),
            status_code=status.HTTP_200_OK,
        )


# ── Detail ────────────────────────────────────────────────────────────────────

class CreditNoteDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(
            CreditNote.objects.select_related("invoice", "issued_by", "cancelled_by")
            .prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        credit_note = self.get_object(request, pk)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Credit note retrieved successfully.",
            data=CreditNoteDetailSerializer(credit_note).data,
            status_code=status.HTTP_200_OK,
        )


class CreditNotePreviewHtmlAPIView(APIView):
    """GET /api/v1/credit-notes/{id}/preview-html/ — HTML for the PDF preview iframe."""

    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        credit_note = get_object_or_404(
            CreditNote.objects.select_related("invoice", "invoice__tenant").prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

        from django.http import HttpResponse
        from apps.platform.credit_notes.pdf_generator import render_credit_note_preview_html
        html = render_credit_note_preview_html(credit_note)
        return HttpResponse(html, content_type="text/html")


class CreditNotePdfAPIView(APIView):
    """POST /api/v1/credit-notes/{id}/generate-pdf/?force=true"""

    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        credit_note = get_object_or_404(
            CreditNote.objects.select_related("invoice").prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

        force = _bool_param(request, "force")
        already_had_pdf = bool(credit_note.pdf_key) and not force

        try:
            pdf_key = CreditNotePdfService.generate_and_store(credit_note, force=force)
        except PdfNotAvailableError as exc:
            return error_response(
                request, code="PDF_DEPENDENCY_MISSING", message=str(exc),
                error="playwright must be installed to generate PDFs.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PdfGenerationError as exc:
            return error_response(
                request, code="PDF_GENERATION_FAILED", message=str(exc),
                error="An error occurred while generating the credit note PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_url = CreditNotePdfService.resolve_url(pdf_key)
        generated = not already_had_pdf
        return success_response(
            request,
            code="PDF_READY",
            message="Credit note PDF is ready.",
            data={"pdf_url": pdf_url, "generated": generated},
            status_code=status.HTTP_200_OK if already_had_pdf else status.HTTP_201_CREATED,
        )


# ── Refund / cancel ───────────────────────────────────────────────────────────

class CreditNoteMarkRefundedAPIView(APIView):
    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        credit_note = get_object_or_404(CreditNote, pk=pk, tenant_id=tenant_id)

        serializer = MarkRefundedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        try:
            credit_note = CreditNoteService.mark_refunded(credit_note, reason=reason)
        except InvalidCreditNoteRefundState as exc:
            return error_response(
                request, code="INVALID_REFUND_STATE", message=str(exc),
                error=str(exc), status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_credit_note_event(request, credit_note, "CREDIT_NOTE_REFUNDED")

        credit_note = CreditNote.objects.select_related("invoice").prefetch_related("line_items").get(pk=credit_note.pk)
        return success_response(
            request,
            code="CREDIT_NOTE_REFUNDED",
            message="Credit note marked as refunded.",
            data=CreditNoteDetailSerializer(credit_note).data,
            status_code=status.HTTP_200_OK,
        )


class CreditNoteCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        credit_note = get_object_or_404(CreditNote, pk=pk, tenant_id=tenant_id)

        serializer = CancelCreditNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        try:
            credit_note = CreditNoteService.cancel(credit_note, cancelled_by=request.user, reason=reason)
        except CreditNoteAlreadyCancelled as exc:
            return error_response(
                request, code="CREDIT_NOTE_ALREADY_CANCELLED", message=str(exc),
                error="This credit note has already been cancelled.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        except CreditNoteAlreadyRefunded as exc:
            return error_response(
                request, code="CREDIT_NOTE_ALREADY_REFUNDED", message=str(exc),
                error="A credit note already marked refunded cannot be cancelled.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_credit_note_event(request, credit_note, "CREDIT_NOTE_CANCELLED")

        credit_note = CreditNote.objects.select_related("invoice").prefetch_related("line_items").get(pk=credit_note.pk)
        return success_response(
            request,
            code="CREDIT_NOTE_CANCELLED",
            message=f"Credit note {credit_note.credit_note_number} cancelled successfully.",
            data=CreditNoteDetailSerializer(credit_note).data,
            status_code=status.HTTP_200_OK,
        )


# ── Reason Categories (tenant-curated master, managed in Configuration) ──────

def _is_archive_flag(request) -> bool:
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


def _is_active_flag(request):
    value = request.query_params.get("is_active")
    if value is None:
        return None
    return str(value).strip().lower() in {"true", "1", "yes"}


class CreditNoteReasonCategoryListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = CreditNoteReasonCategory.objects.filter(
            tenant_id=tenant_id, is_archived=_is_archive_flag(request)
        ).order_by("sort_order", "name")
        is_active = _is_active_flag(request)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Reason categories retrieved successfully.",
            data=build_paginated_data(request, queryset, CreditNoteReasonCategorySerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = CreditNoteReasonCategorySerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request, code="INTEGRITY_ERROR", message="Could not create reason category.",
                error=reason_category_integrity_errors(exc), status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request, code="REASON_CATEGORY_CREATED", message="Reason category created successfully.",
            data=serializer.data, status_code=status.HTTP_201_CREATED,
        )


class CreditNoteReasonCategoryDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedCreditNoteAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(CreditNoteReasonCategory, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = CreditNoteReasonCategorySerializer(self.get_object(request, pk))
        return success_response(
            request, code="DATA_RETRIEVED", message="Reason category retrieved successfully.",
            data=serializer.data, status_code=status.HTTP_200_OK,
        )

    def _update(self, request, pk, *, partial):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = CreditNoteReasonCategorySerializer(
            instance, data=payload, partial=partial, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request, code="INTEGRITY_ERROR", message="Could not update reason category.",
                error=reason_category_integrity_errors(exc), status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request, code="REASON_CATEGORY_UPDATED", message="Reason category updated successfully.",
            data=serializer.data, status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def delete(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        category = get_object_or_404(CreditNoteReasonCategory, pk=pk, tenant_id=tenant_id, is_archived=False)
        # reason_category on CreditNote is a text snapshot, not an FK — no
        # dependents to unlink, unlike LabourCategory's ServiceItem case.
        category.archive()
        return success_response(
            request, code="REASON_CATEGORY_DELETED", message="Reason category archived successfully.",
            data={}, status_code=status.HTTP_200_OK,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_credit_note_event(request, credit_note: CreditNote, action: str) -> None:
    """Swallowed on failure so it never breaks the response."""
    try:
        from core.audit.service import log_audit_event
        log_audit_event(
            actor_id=str(request.user.pk),
            actor_type="user",
            action=action,
            module="CREDIT_NOTE",
            ip_address=_get_client_ip(request),
            method=request.method,
            endpoint=request.path,
            after={"credit_note_id": str(credit_note.pk), "credit_note_number": credit_note.credit_note_number},
        )
    except Exception:
        pass


def _get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
