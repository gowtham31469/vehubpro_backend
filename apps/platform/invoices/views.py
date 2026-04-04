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
    GenerateInvoiceSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    RecordPaymentSerializer,
)
from apps.platform.invoices.service import (
    InvoiceAlreadyExists,
    InvalidJobCardStatus,
    InvoiceService,
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
            .order_by("-created_at")
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


def _get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
