"""
Invoice views.

Endpoints
---------
POST   /api/v1/job-cards/{job_card_id}/generate-invoice/
           Convert a completed job card into a GST invoice.
GET    /api/v1/invoices/
           List all invoices for the authenticated tenant (compact, no PII).
GET    /api/v1/invoices/{id}/
           Full invoice detail including decrypted customer PII (access logged).
PATCH  /api/v1/invoices/{id}/record-payment/
           Record or update a payment against an invoice.

Audit / compliance
------------------
- GET detail view logs a PII_ACCESS event via the platform audit service.
- Generate action logs an INVOICE_GENERATED event.
- Record payment logs a PAYMENT_RECORDED event.
- All views enforce tenant isolation: only invoices belonging to request.user.tenant_id
  are ever returned or mutated.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.invoices.models import Invoice
from apps.platform.invoices.permissions import IsAuthenticatedInvoiceAccess
from apps.platform.invoices.serializers import (
    CancelInvoiceSerializer,
    GenerateInvoiceSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    RecordPaymentSerializer,
)
from apps.platform.invoices.service import (
    InvoiceAlreadyCancelled,
    InvoiceAlreadyExists,
    InvoiceHasPayments,
    InvalidJobCardStatus,
    InvoiceService,
)
from apps.platform.invoices.pdf_service import (
    InvoicePdfService,
    PdfGenerationError,
    PdfNotAvailableError,
)
from apps.platform.jobcards.models import JobCard
from apps.platform.jobcards.permissions import IsAuthenticatedJobCardAccess
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


# ── Generate invoice from a job card ─────────────────────────────────────────

class GenerateInvoiceAPIView(APIView):
    """
    POST /api/v1/job-cards/{job_card_id}/generate-invoice/

    Converts a completed job card into an immutable GST invoice.
    The job card's status changes from 'completed' → 'invoiced' atomically.

    Request body (optional JSON):
        { "notes": "..." }

    Responses:
        201  Invoice created — returns full invoice detail.
        400  Job card is not in 'completed' status, or tenant context missing.
        409  Invoice already exists for this job card.
        404  Job card not found (or belongs to a different tenant).
    """

    permission_classes = [IsAuthenticatedJobCardAccess]

    def post(self, request, job_card_id):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        job_card = get_object_or_404(
            JobCard.objects.select_related(
                "customer__state",
                "customer__city",
                "vehicle__brand",
                "vehicle__vehicle_model",
                "tenant__pii",
            ).prefetch_related("line_items__service_item"),
            pk=job_card_id,
            tenant_id=tenant_id,
        )

        serializer = GenerateInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notes = serializer.validated_data.get("notes", "")

        try:
            invoice = InvoiceService.generate(job_card, issued_by=request.user)
        except InvalidJobCardStatus as exc:
            return error_response(
                request,
                code="INVALID_JOB_CARD_STATUS",
                message=str(exc),
                error="Job card must be in 'completed' status to generate an invoice.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvoiceAlreadyExists as exc:
            return error_response(
                request,
                code="INVOICE_ALREADY_EXISTS",
                message=str(exc),
                error="An invoice already exists for this job card.",
                status_code=status.HTTP_409_CONFLICT,
            )

        if notes:
            Invoice.objects.filter(pk=invoice.pk).update(notes=notes)
            invoice.notes = notes

        # Reload with line items for the response
        invoice = (
            Invoice.objects.select_related("job_card", "issued_by")
            .prefetch_related("line_items")
            .get(pk=invoice.pk)
        )

        return success_response(
            request,
            code="INVOICE_GENERATED",
            message=f"Invoice {invoice.invoice_number} generated successfully.",
            data=InvoiceDetailSerializer(invoice).data,
            status_code=status.HTTP_201_CREATED,
        )


# ── Invoice list ──────────────────────────────────────────────────────────────

class InvoiceListAPIView(APIView):
    """
    GET /api/v1/invoices/

    Returns a paginated, tenant-scoped list of invoices (compact — no PII, no line items).

    Query parameters:
        payment_status  Filter by payment_status (unpaid | partial | paid).
        fy_code         Filter by financial year code (e.g. "25-26").
        search          Prefix search on invoice_number or vehicle registration snapshot.
        page            Page number (default 1).
        page_size       Page size (default 10, max 100).
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = (
            Invoice.objects.filter(tenant_id=tenant_id)
            .select_related("job_card")
            .order_by("-created_at", "-invoice_number")
        )

        payment_status = request.query_params.get("payment_status", "").strip()
        if payment_status in {Invoice.PAYMENT_STATUS_UNPAID, Invoice.PAYMENT_STATUS_PARTIAL, Invoice.PAYMENT_STATUS_PAID}:
            queryset = queryset.filter(payment_status=payment_status)

        fy_code = request.query_params.get("fy_code", "").strip()
        if fy_code:
            queryset = queryset.filter(fy_code=fy_code)

        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(invoice_number__icontains=search)
                | Q(vehicle_registration_no_snapshot__icontains=search)
            )

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Invoices retrieved successfully.",
            data=build_paginated_data(request, queryset, InvoiceListSerializer),
            status_code=status.HTTP_200_OK,
        )


# ── Invoice detail ────────────────────────────────────────────────────────────

class InvoiceDetailAPIView(APIView):
    """
    GET  /api/v1/invoices/{id}/
         Full invoice detail including decrypted customer PII. Access is logged.

    PATCH /api/v1/invoices/{id}/
         Update invoice signatures and metadata (customer_signature, admin_signature, etc).
         Financial totals cannot be modified (immutable after issuance).

    PATCH /api/v1/invoices/{id}/record-payment/
          Handled by RecordPaymentAPIView below (separate URL).
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def _get_invoice(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(
            Invoice.objects.select_related("job_card", "issued_by")
            .prefetch_related("line_items", "payments"),
            pk=pk,
            tenant_id=tenant_id,
        )

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = self._get_invoice(request, pk)

        # ISO 27001 / DPDP: log PII access on every detail view
        _log_pii_access(request, invoice)

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Invoice retrieved successfully.",
            data=InvoiceDetailSerializer(invoice).data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = self._get_invoice(request, pk)

        # Only allow updating signature and metadata fields, not financial totals
        allowed_fields = {
            'customer_signature',
            'customer_signature_date',
            'admin_signature',
            'admin_signature_date',
        }

        updates = {}
        for field in allowed_fields:
            if field in request.data:
                updates[field] = request.data[field]

        if updates:
            Invoice.objects.filter(pk=invoice.pk).update(**updates)
            for field, value in updates.items():
                setattr(invoice, field, value)

        return success_response(
            request,
            code="INVOICE_UPDATED",
            message="Invoice updated successfully.",
            data=InvoiceDetailSerializer(invoice).data,
            status_code=status.HTTP_200_OK,
        )


class InvoicePreviewHtmlAPIView(APIView):
    """
    GET /api/v1/invoices/{id}/preview-html/

    Returns the raw HTML used to generate the invoice PDF (same template, same
    data), for embedding in an iframe. This keeps the in-app preview guaranteed
    pixel-identical to the downloaded PDF instead of a hand-maintained,
    drift-prone React replica.
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = get_object_or_404(
            Invoice.objects.select_related("tenant", "job_card").prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

        # ISO 27001 / DPDP: rendering the preview decrypts PII, same as the PDF.
        _log_pii_access(request, invoice)

        from django.http import HttpResponse

        from apps.platform.invoices.pdf_generator import render_invoice_preview_html
        html = render_invoice_preview_html(invoice)
        return HttpResponse(html, content_type="text/html")


# ── Record payment ────────────────────────────────────────────────────────────

class RecordPaymentAPIView(APIView):
    """
    PATCH /api/v1/invoices/{id}/record-payment/

    Record or update a payment against an invoice.
    Derives payment_status automatically from amount_paid vs total_amount.

    Request body:
        {
            "payment_mode": "upi",
            "amount_paid": "1500.00",
            "payment_reference": "UPI-TXN-12345"   (optional)
        }
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = get_object_or_404(
            Invoice.objects.select_related("job_card"),
            pk=pk,
            tenant_id=tenant_id,
        )

        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        invoice = InvoiceService.record_payment(
            invoice,
            payment_mode=vd["payment_mode"],
            amount_paid=vd["amount_paid"],
            payment_reference=vd.get("payment_reference", ""),
            recorded_by=request.user,
        )

        return success_response(
            request,
            code="PAYMENT_RECORDED",
            message="Payment recorded successfully.",
            data=InvoiceDetailSerializer(invoice).data,
            status_code=status.HTTP_200_OK,
        )


# ── Cancel invoice ────────────────────────────────────────────────────────────

class InvoiceCancelAPIView(APIView):
    """
    PATCH /api/v1/invoices/{id}/cancel/

    Voids an invoice without deleting it (GST retention requirements). The
    linked job card, if still 'invoiced', reverts to 'completed' so a fresh
    invoice can be generated for it later.

    Request body (optional JSON):
        { "reason": "..." }

    Responses:
        200  Invoice cancelled — returns full invoice detail.
        400  Invoice already cancelled, has payments recorded, or tenant context missing.
        404  Invoice not found (or belongs to a different tenant).
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = get_object_or_404(
            Invoice.objects.select_related("job_card"),
            pk=pk,
            tenant_id=tenant_id,
        )

        serializer = CancelInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        try:
            invoice = InvoiceService.cancel(invoice, cancelled_by=request.user, reason=reason)
        except InvoiceAlreadyCancelled as exc:
            return error_response(
                request,
                code="INVOICE_ALREADY_CANCELLED",
                message=str(exc),
                error="This invoice has already been cancelled.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvoiceHasPayments as exc:
            return error_response(
                request,
                code="INVOICE_HAS_PAYMENTS",
                message=str(exc),
                error="Invoices with recorded payments cannot be cancelled.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_cancel(request, invoice, reason)

        return success_response(
            request,
            code="INVOICE_CANCELLED",
            message=f"Invoice {invoice.invoice_number} cancelled successfully.",
            data=InvoiceDetailSerializer(invoice).data,
            status_code=status.HTTP_200_OK,
        )


# ── PDF download ─────────────────────────────────────────────────────────────

class InvoicePdfAPIView(APIView):
    """
    POST /api/v1/invoices/{id}/generate-pdf/

    Generates (or returns the cached) PDF for an invoice and returns its URL.

    Query params
    ------------
    force   "true" to regenerate even if a PDF already exists (e.g. after
            payment status changes). Defaults to false.

    Response
    --------
    200  { "pdf_url": "...", "generated": false }   — existing PDF returned
    201  { "pdf_url": "...", "generated": true  }   — freshly generated PDF

    Compliance
    ----------
    - PII_ACCESS audit event is logged (PDF decrypts customer PII at render time).
    - If invoice.is_pii_erased is True, the PDF is generated with [DATA ERASED]
      placeholders so the file contains no personal data.
    - On S3: pdf_url is a pre-signed, time-limited URL (AWS_S3_PRESIGN_EXPIRES_SECONDS).
    - On LOCAL: pdf_url is an absolute URL via BASE_URL + MEDIA_URL.
    """

    permission_classes = [IsAuthenticatedInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        invoice = get_object_or_404(
            Invoice.objects.select_related("job_card").prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

        force = request.query_params.get("force", "false").lower() in {"true", "1", "yes"}
        already_had_pdf = bool(invoice.pdf_key) and not force

        # Audit — generating the PDF decrypts PII at render time
        _log_pii_access(request, invoice)

        try:
            pdf_key = InvoicePdfService.generate_and_store(invoice, force=force)
        except PdfNotAvailableError as exc:
            return error_response(
                request,
                code="PDF_DEPENDENCY_MISSING",
                message=str(exc),
                error="weasyprint must be installed to generate PDFs.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PdfGenerationError as exc:
            return error_response(
                request,
                code="PDF_GENERATION_FAILED",
                message=str(exc),
                error="An error occurred while generating the invoice PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_url = InvoicePdfService.resolve_url(pdf_key)
        generated = not already_had_pdf
        return success_response(
            request,
            code="PDF_READY",
            message="Invoice PDF is ready.",
            data={"pdf_url": pdf_url, "generated": generated},
            status_code=status.HTTP_200_OK if already_had_pdf else status.HTTP_201_CREATED,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_pii_access(request, invoice: Invoice) -> None:
    """
    Write a PII_ACCESS audit event. Swallowed on failure so it never breaks the response.
    Extend this once the platform audit service supports PII_ACCESS action type.
    """
    try:
        from core.audit.service import log_audit_event
        log_audit_event(
            actor_id=str(request.user.pk),
            actor_type="user",
            action="PII_ACCESS",
            module="INVOICE",
            ip_address=_get_client_ip(request),
            method=request.method,
            endpoint=request.path,
            after={"invoice_id": str(invoice.pk), "invoice_number": invoice.invoice_number},
        )
    except Exception:
        pass


def _log_cancel(request, invoice: Invoice, reason: str) -> None:
    """Write an INVOICE_CANCELLED audit event. Swallowed on failure so it never breaks the response."""
    try:
        from core.audit.service import log_audit_event
        log_audit_event(
            actor_id=str(request.user.pk),
            actor_type="user",
            action="INVOICE_CANCELLED",
            module="INVOICE",
            ip_address=_get_client_ip(request),
            method=request.method,
            endpoint=request.path,
            after={"invoice_id": str(invoice.pk), "invoice_number": invoice.invoice_number, "reason": reason},
        )
    except Exception:
        pass


def _get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
