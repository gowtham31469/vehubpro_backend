"""
Proforma Invoice / Advance Payment views.

Endpoints
---------
POST   /api/v1/job-cards/{job_card_id}/generate-proforma-invoice/
GET    /api/v1/proforma-invoices/
GET    /api/v1/proforma-invoices/{id}/
POST   /api/v1/proforma-invoices/{id}/issue/
POST   /api/v1/proforma-invoices/{id}/approve/
POST   /api/v1/proforma-invoices/{id}/reject/
POST   /api/v1/proforma-invoices/{id}/cancel/
POST   /api/v1/proforma-invoices/{id}/revise/
GET    /api/v1/proforma-invoices/{id}/revisions/
POST   /api/v1/proforma-invoices/{id}/convert/
GET    /api/v1/proforma-invoices/{id}/preview-html/
POST   /api/v1/proforma-invoices/{id}/generate-pdf/
GET    /api/v1/proforma-invoices/{id}/advance-payments/
POST   /api/v1/proforma-invoices/{id}/advance-payments/
POST   /api/v1/advance-payments/{id}/mark-received/
POST   /api/v1/advance-payments/{id}/reverse/
POST   /api/v1/advance-payments/{id}/refund/
GET    /api/v1/advance-payments/{id}/receipt/preview-html/
POST   /api/v1/advance-payments/{id}/receipt/generate-pdf/

All views enforce tenant isolation: only rows belonging to
request.user.tenant_id are ever returned or mutated.
"""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.jobcards.models import JobCard
from apps.platform.jobcards.permissions import IsAuthenticatedJobCardAccess
from apps.platform.proforma_invoices.models import AdvancePayment, ProformaInvoice
from apps.platform.proforma_invoices.permissions import IsAuthenticatedProformaInvoiceAccess
from apps.platform.proforma_invoices.serializers import (
    AdvancePaymentSerializer,
    GenerateProformaInvoiceSerializer,
    ProformaInvoiceDetailSerializer,
    ProformaInvoiceListSerializer,
    ReasonInputSerializer,
    RecordAdvancePaymentSerializer,
    ReviseProformaInvoiceSerializer,
)
from apps.platform.proforma_invoices.service import (
    AdvancePaymentAlreadyApplied,
    AdvancePaymentService,
    InvalidAdvancePaymentAmount,
    InvalidAdvancePaymentStatus,
    InvalidJobCardForProforma,
    InvalidProformaStatus,
    InvalidProformaStatusForAdvance,
    ProformaAlreadyConverted,
    ProformaInvoiceAlreadyActive,
    ProformaInvoiceService,
    ProformaNotLatestVersion,
    ProformaRevisionNotAllowed,
)
from apps.platform.invoices.models import Invoice
from apps.platform.invoices.serializers import InvoiceDetailSerializer
from apps.platform.invoices.service import InvalidJobCardStatus, InvoiceAlreadyExists
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


def _resolve_proforma(request, pk):
    tenant_id = getattr(request.user, "tenant_id", None)
    return get_object_or_404(
        ProformaInvoice.objects.select_related("job_card", "customer", "vehicle", "created_by")
        .prefetch_related("line_items", "advance_payments"),
        pk=pk,
        tenant_id=tenant_id,
    )


def _resolve_advance_payment(request, pk):
    tenant_id = getattr(request.user, "tenant_id", None)
    return get_object_or_404(
        AdvancePayment.objects.select_related("proforma_invoice", "job_card"),
        pk=pk,
        tenant_id=tenant_id,
    )


# ── Generate proforma invoice from a job card ───────────────────────────────

class ProformaInvoiceGenerateAPIView(APIView):
    """POST /api/v1/job-cards/{job_card_id}/generate-proforma-invoice/"""

    permission_classes = [IsAuthenticatedJobCardAccess]

    def post(self, request, job_card_id):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        job_card = get_object_or_404(
            JobCard.objects.select_related("customer", "vehicle", "tenant__pii", "tenant__invoice_settings")
            .prefetch_related("line_items__service_item"),
            pk=job_card_id,
            tenant_id=tenant_id,
        )

        serializer = GenerateProformaInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice_type = serializer.validated_data["invoice_type"]

        try:
            proforma = ProformaInvoiceService.generate(job_card, created_by=request.user, invoice_type=invoice_type)
        except InvalidJobCardForProforma as exc:
            return error_response(
                request, code="INVALID_JOB_CARD_FOR_PROFORMA", message=str(exc),
                error="This job card cannot have a proforma invoice generated.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except ProformaInvoiceAlreadyActive as exc:
            return error_response(
                request, code="PROFORMA_INVOICE_ALREADY_ACTIVE", message=str(exc),
                error="This job card already has an active proforma invoice — revise it instead.",
                status_code=status.HTTP_409_CONFLICT,
            )

        proforma = _resolve_proforma(request, proforma.pk)
        return success_response(
            request, code="PROFORMA_INVOICE_GENERATED",
            message=f"Proforma invoice {proforma.proforma_number} generated successfully.",
            data=ProformaInvoiceDetailSerializer(proforma).data,
            status_code=status.HTTP_201_CREATED,
        )


# ── List ──────────────────────────────────────────────────────────────────

class ProformaInvoiceListAPIView(APIView):
    """GET /api/v1/proforma-invoices/?status=&job_card=&is_latest="""

    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = ProformaInvoice.objects.filter(tenant_id=tenant_id).select_related(
            "job_card", "customer", "vehicle"
        )

        status_param = request.query_params.get("status", "").strip()
        if status_param in dict(ProformaInvoice.STATUS_CHOICES):
            queryset = queryset.filter(status=status_param)

        job_card_id = request.query_params.get("job_card", "").strip()
        if job_card_id:
            queryset = queryset.filter(job_card_id=job_card_id)

        is_latest_param = request.query_params.get("is_latest", "true").strip().lower()
        if is_latest_param in {"true", "1", "yes"}:
            queryset = queryset.filter(is_latest=True)

        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(proforma_number__icontains=search)
                | Q(customer__full_name__icontains=search)
                | Q(vehicle__registration_no__icontains=search)
            )

        queryset = queryset.order_by("-created_at", "-proforma_number")

        return success_response(
            request, code="DATA_RETRIEVED", message="Proforma invoices retrieved successfully.",
            data=build_paginated_data(request, queryset, ProformaInvoiceListSerializer),
            status_code=status.HTTP_200_OK,
        )


# ── Detail ────────────────────────────────────────────────────────────────

class ProformaInvoiceDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)
        ProformaInvoiceService.apply_expiry_if_due(proforma)
        return success_response(
            request, code="DATA_RETRIEVED", message="Proforma invoice retrieved successfully.",
            data=ProformaInvoiceDetailSerializer(proforma).data, status_code=status.HTTP_200_OK,
        )


def _status_transition_view(request, pk, *, action, serializer_class=None):
    """Shared plumbing for the simple status-transition endpoints below —
    resolves the proforma, validates the (optional) body, runs `action`,
    and wraps the known service exceptions into the standard error envelope."""
    tenant_id, error = _tenant_context(request)
    if error:
        return error
    proforma = _resolve_proforma(request, pk)

    extra_kwargs = {}
    if serializer_class:
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        extra_kwargs = dict(serializer.validated_data)

    try:
        proforma = action(proforma, **extra_kwargs)
    except InvalidProformaStatus as exc:
        return error_response(
            request, code="INVALID_PROFORMA_STATUS", message=str(exc), error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except InvalidJobCardForProforma as exc:
        return error_response(
            request, code="INVALID_JOB_CARD_FOR_PROFORMA", message=str(exc), error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except ProformaNotLatestVersion as exc:
        return error_response(
            request, code="PROFORMA_NOT_LATEST_VERSION", message=str(exc), error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except ProformaRevisionNotAllowed as exc:
        return error_response(
            request, code="PROFORMA_REVISION_NOT_ALLOWED", message=str(exc), error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    proforma = _resolve_proforma(request, proforma.pk)
    return success_response(
        request, code="PROFORMA_INVOICE_UPDATED", message="Proforma invoice updated successfully.",
        data=ProformaInvoiceDetailSerializer(proforma).data, status_code=status.HTTP_200_OK,
    )


class ProformaInvoiceIssueAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        return _status_transition_view(request, pk, action=lambda p: ProformaInvoiceService.issue(p))


class ProformaInvoiceApproveAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        return _status_transition_view(request, pk, action=lambda p: ProformaInvoiceService.approve(p))


class ProformaInvoiceRejectAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        return _status_transition_view(
            request, pk,
            action=lambda p, reason="": ProformaInvoiceService.reject(p, reason=reason),
            serializer_class=ReasonInputSerializer,
        )


class ProformaInvoiceCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        return _status_transition_view(
            request, pk,
            action=lambda p, reason="": ProformaInvoiceService.cancel(p, reason=reason),
            serializer_class=ReasonInputSerializer,
        )


class ProformaInvoiceReviseAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        return _status_transition_view(
            request, pk,
            action=lambda p, revision_reason: ProformaInvoiceService.create_revision(
                p, revision_reason=revision_reason, created_by=request.user,
            ),
            serializer_class=ReviseProformaInvoiceSerializer,
        )


class ProformaInvoiceRevisionsAPIView(APIView):
    """GET /api/v1/proforma-invoices/{id}/revisions/ — the full version family
    (same proforma_number across tenant), oldest first."""

    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)
        family = ProformaInvoice.objects.filter(
            tenant_id=tenant_id, proforma_number=proforma.proforma_number
        ).select_related("job_card", "customer", "vehicle").order_by("version")
        return success_response(
            request, code="DATA_RETRIEVED", message="Proforma invoice revisions retrieved successfully.",
            data=ProformaInvoiceListSerializer(family, many=True).data, status_code=status.HTTP_200_OK,
        )


# ── Convert to invoice ───────────────────────────────────────────────────────

class ProformaInvoiceConvertAPIView(APIView):
    """POST /api/v1/proforma-invoices/{id}/convert/"""

    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)

        try:
            invoice = ProformaInvoiceService.convert_to_invoice(proforma, issued_by=request.user)
        except ProformaAlreadyConverted as exc:
            return error_response(
                request, code="PROFORMA_ALREADY_CONVERTED", message=str(exc), error=str(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        except ProformaNotLatestVersion as exc:
            return error_response(
                request, code="PROFORMA_NOT_LATEST_VERSION", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidProformaStatus as exc:
            return error_response(
                request, code="INVALID_PROFORMA_STATUS", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidJobCardStatus as exc:
            return error_response(
                request, code="INVALID_JOB_CARD_STATUS", message=str(exc),
                error="The job card must be in 'completed' status to generate the final invoice.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvoiceAlreadyExists as exc:
            return error_response(
                request, code="INVOICE_ALREADY_EXISTS", message=str(exc), error=str(exc),
                status_code=status.HTTP_409_CONFLICT,
            )

        invoice = Invoice.objects.select_related("job_card", "issued_by").prefetch_related(
            "line_items", "payments"
        ).get(pk=invoice.pk)

        return success_response(
            request, code="PROFORMA_INVOICE_CONVERTED",
            message=f"Proforma invoice converted to invoice {invoice.invoice_number} successfully.",
            data=InvoiceDetailSerializer(invoice).data, status_code=status.HTTP_201_CREATED,
        )


# ── PDF preview / download ───────────────────────────────────────────────────

class ProformaInvoicePreviewHtmlAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)
        from apps.platform.proforma_invoices.pdf_generator import render_proforma_invoice_preview_html
        html = render_proforma_invoice_preview_html(proforma)
        return HttpResponse(html, content_type="text/html")


class ProformaInvoicePdfAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)

        force = request.query_params.get("force", "false").strip().lower() in {"true", "1", "yes"}
        already_had_pdf = bool(proforma.pdf_key) and not force

        from apps.platform.proforma_invoices.pdf_service import (
            PdfGenerationError,
            PdfNotAvailableError,
            ProformaInvoicePdfService,
        )
        try:
            pdf_key = ProformaInvoicePdfService.generate_and_store(proforma, force=force)
        except PdfNotAvailableError as exc:
            return error_response(
                request, code="PDF_DEPENDENCY_MISSING", message=str(exc),
                error="playwright must be installed to generate PDFs.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PdfGenerationError as exc:
            return error_response(
                request, code="PDF_GENERATION_FAILED", message=str(exc),
                error="An error occurred while generating the proforma invoice PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_url = ProformaInvoicePdfService.resolve_url(pdf_key)
        return success_response(
            request, code="PDF_READY", message="Proforma invoice PDF is ready.",
            data={"pdf_url": pdf_url, "generated": not already_had_pdf},
            status_code=status.HTTP_200_OK if already_had_pdf else status.HTTP_201_CREATED,
        )


# ── Advance payments ──────────────────────────────────────────────────────────

class AdvancePaymentListCreateAPIView(APIView):
    """GET/POST /api/v1/proforma-invoices/{id}/advance-payments/"""

    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)
        queryset = proforma.advance_payments.order_by("created_at")
        return success_response(
            request, code="DATA_RETRIEVED", message="Advance payments retrieved successfully.",
            data=build_paginated_data(request, queryset, AdvancePaymentSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        proforma = _resolve_proforma(request, pk)

        serializer = RecordAdvancePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        try:
            payment = AdvancePaymentService.record(
                proforma,
                amount=vd["amount"],
                payment_mode=vd["payment_mode"],
                payment_reference=vd.get("payment_reference", ""),
                received_by=request.user,
                remarks=vd.get("remarks", ""),
            )
        except InvalidProformaStatusForAdvance as exc:
            return error_response(
                request, code="INVALID_PROFORMA_STATUS_FOR_ADVANCE", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidAdvancePaymentAmount as exc:
            return error_response(
                request, code="INVALID_ADVANCE_PAYMENT_AMOUNT", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return success_response(
            request, code="ADVANCE_PAYMENT_RECORDED", message="Advance payment recorded successfully.",
            data=AdvancePaymentSerializer(payment).data, status_code=status.HTTP_201_CREATED,
        )


class AdvancePaymentMarkReceivedAPIView(APIView):
    """POST /api/v1/advance-payments/{id}/mark-received/ — gateway-mode only."""

    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payment = _resolve_advance_payment(request, pk)
        try:
            payment = AdvancePaymentService.mark_received(payment, received_by=request.user)
        except InvalidAdvancePaymentStatus as exc:
            return error_response(
                request, code="INVALID_ADVANCE_PAYMENT_STATUS", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(
            request, code="ADVANCE_PAYMENT_UPDATED", message="Advance payment marked as received.",
            data=AdvancePaymentSerializer(payment).data, status_code=status.HTTP_200_OK,
        )


class AdvancePaymentReverseAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payment = _resolve_advance_payment(request, pk)
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = AdvancePaymentService.reverse(payment, reason=serializer.validated_data.get("reason", ""))
        except (InvalidAdvancePaymentStatus, AdvancePaymentAlreadyApplied) as exc:
            return error_response(
                request, code="ADVANCE_PAYMENT_REVERSE_FAILED", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(
            request, code="ADVANCE_PAYMENT_UPDATED", message="Advance payment reversed.",
            data=AdvancePaymentSerializer(payment).data, status_code=status.HTTP_200_OK,
        )


class AdvancePaymentRefundAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payment = _resolve_advance_payment(request, pk)
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = AdvancePaymentService.refund(payment, reason=serializer.validated_data.get("reason", ""))
        except (InvalidAdvancePaymentStatus, AdvancePaymentAlreadyApplied) as exc:
            return error_response(
                request, code="ADVANCE_PAYMENT_REFUND_FAILED", message=str(exc), error=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(
            request, code="ADVANCE_PAYMENT_UPDATED", message="Advance payment refunded.",
            data=AdvancePaymentSerializer(payment).data, status_code=status.HTTP_200_OK,
        )


class AdvanceReceiptPreviewHtmlAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payment = _resolve_advance_payment(request, pk)
        if not payment.receipt_number:
            return error_response(
                request, code="RECEIPT_NOT_AVAILABLE", message="No receipt number has been allocated for this payment yet.",
                error="This payment is not in a 'received' state.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        from apps.platform.proforma_invoices.pdf_generator import render_advance_receipt_html
        html = render_advance_receipt_html(payment)
        return HttpResponse(html, content_type="text/html")


class AdvanceReceiptPdfAPIView(APIView):
    permission_classes = [IsAuthenticatedProformaInvoiceAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payment = _resolve_advance_payment(request, pk)

        force = request.query_params.get("force", "false").strip().lower() in {"true", "1", "yes"}
        already_had_pdf = bool(payment.receipt_pdf_key) and not force

        from apps.platform.proforma_invoices.pdf_service import (
            AdvanceReceiptPdfService,
            PdfGenerationError,
            PdfNotAvailableError,
        )
        try:
            pdf_key = AdvanceReceiptPdfService.generate_and_store(payment, force=force)
        except PdfNotAvailableError as exc:
            return error_response(
                request, code="PDF_DEPENDENCY_MISSING", message=str(exc),
                error="playwright must be installed to generate PDFs.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PdfGenerationError as exc:
            return error_response(
                request, code="PDF_GENERATION_FAILED", message=str(exc),
                error="An error occurred while generating the receipt PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_url = AdvanceReceiptPdfService.resolve_url(pdf_key)
        return success_response(
            request, code="PDF_READY", message="Advance payment receipt PDF is ready.",
            data={"pdf_url": pdf_url, "generated": not already_had_pdf},
            status_code=status.HTTP_200_OK if already_had_pdf else status.HTTP_201_CREATED,
        )
