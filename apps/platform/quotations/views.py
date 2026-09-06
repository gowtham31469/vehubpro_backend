"""
Quotation views.

Endpoints
---------
GET/POST   /api/v1/quotations/
GET/PATCH/DELETE /api/v1/quotations/{id}/
PATCH      /api/v1/quotations/{id}/send/
PATCH      /api/v1/quotations/{id}/approve/
PATCH      /api/v1/quotations/{id}/reject/
PATCH      /api/v1/quotations/{id}/cancel/
POST       /api/v1/quotations/{id}/revise/
GET        /api/v1/quotations/{id}/revisions/
POST       /api/v1/quotations/{id}/convert-to-job-card/
GET        /api/v1/quotations/{id}/preview-html/
POST       /api/v1/quotations/{id}/generate-pdf/

Tenant isolation: every queryset is filtered by request.user.tenant_id, same
pattern as jobcards/invoices — there is no shared tenant-scoping mixin in this
codebase to inherit from.
"""
from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.jobcards.serializers import JobCardSerializer
from apps.platform.quotations.models import Quotation
from apps.platform.quotations.permissions import IsAuthenticatedQuotationAccess
from apps.platform.quotations.serializers import (
    CancelQuotationSerializer,
    QuotationSerializer,
    RejectQuotationSerializer,
    RevisionActionSerializer,
)
from apps.platform.quotations.service import (
    InvalidQuotationStatus,
    QuotationAlreadyConverted,
    QuotationNotLatestVersion,
    QuotationRevisionNotAllowed,
    QuotationService,
)
from core.utils.api_response import error_response, success_response

_SELECT_RELATED = (
    "customer",
    "vehicle",
    "vehicle__brand",
    "vehicle__vehicle_model",
    "created_by",
    "parent_quotation",
)


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


def _get_quotation(request, pk, *, for_update_check=False):
    tenant_id = getattr(request.user, "tenant_id", None)
    qs = Quotation.objects.select_related(*_SELECT_RELATED).prefetch_related("line_items")
    quotation = get_object_or_404(qs, pk=pk, tenant_id=tenant_id)
    if for_update_check:
        QuotationService.apply_expiry_if_due(quotation)
    return quotation


class QuotationListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        # Only the latest version of each family shows in the main list —
        # superseded revisions are reachable via the {id}/revisions/ endpoint.
        queryset = (
            Quotation.objects.filter(tenant_id=tenant_id, is_latest=True)
            .select_related(*_SELECT_RELATED)
            .order_by("-created_at", "-quotation_number")
        )

        status_param = request.query_params.get("status", "").strip()
        if status_param in dict(Quotation.STATUS_CHOICES):
            queryset = queryset.filter(status=status_param)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(quotation_number__icontains=search)
                | Q(customer__full_name__icontains=search)
                | Q(vehicle__registration_no__icontains=search)
            )

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Quotations retrieved successfully.",
            data=_paginate(request, queryset),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("quotation_number", None)
        payload.pop("version", None)
        payload.pop("parent_quotation", None)
        payload.pop("is_latest", None)
        payload.pop("status", None)
        serializer = QuotationSerializer(
            data=payload, context={"request": request, "tenant_id": tenant_id, "compact": False}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="QUOTATION_CREATED",
            message="Quotation created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


def _paginate(request, queryset):
    from core.utils.pagination import StandardResultsSetPagination

    paginator = StandardResultsSetPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = QuotationSerializer(page, many=True, context={"compact": True})
    return {
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": serializer.data,
    }


class QuotationDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk, for_update_check=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Quotation retrieved successfully.",
            data=QuotationSerializer(quotation, context={"compact": False}).data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = _get_quotation(request, pk)
        payload = request.data.copy()
        for locked_field in ("tenant", "quotation_number", "version", "parent_quotation", "is_latest", "status"):
            payload.pop(locked_field, None)
        serializer = QuotationSerializer(
            instance, data=payload, partial=True, context={"request": request, "tenant_id": tenant_id}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="QUOTATION_UPDATED",
            message="Quotation updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        instance = _get_quotation(request, pk)
        if instance.status != Quotation.STATUS_DRAFT:
            return error_response(
                request,
                code="QUOTATION_NOT_DRAFT",
                message="Only a draft quotation can be deleted.",
                error=f"Quotation is in '{instance.status}' status.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        instance.delete()
        return success_response(
            request,
            code="QUOTATION_DELETED",
            message="Quotation deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class QuotationRevisionsListAPIView(APIView):
    """GET /api/v1/quotations/{id}/revisions/ — the full version history for this quotation's family."""

    permission_classes = [IsAuthenticatedQuotationAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)
        family = (
            Quotation.objects.filter(tenant_id=tenant_id, quotation_number=quotation.quotation_number)
            .select_related(*_SELECT_RELATED)
            .order_by("version")
        )
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Quotation revision history retrieved successfully.",
            data=QuotationSerializer(family, many=True, context={"compact": True}).data,
            status_code=status.HTTP_200_OK,
        )


class QuotationSendAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def patch(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)
        try:
            quotation = QuotationService.send(quotation)
        except InvalidQuotationStatus as exc:
            return error_response(
                request,
                code="INVALID_QUOTATION_STATUS",
                message=str(exc),
                error="Quotation must be a non-empty draft to send.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        _log_event(request, quotation, "QUOTATION_SENT")
        return success_response(
            request,
            code="QUOTATION_SENT",
            message=f"Quotation {quotation.quotation_number} sent successfully.",
            data=QuotationSerializer(quotation, context={"compact": False}).data,
            status_code=status.HTTP_200_OK,
        )


class QuotationApproveAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def patch(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)
        try:
            quotation = QuotationService.approve(quotation)
        except InvalidQuotationStatus as exc:
            return error_response(
                request,
                code="INVALID_QUOTATION_STATUS",
                message=str(exc),
                error="Quotation must be 'sent' to approve.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        _log_event(request, quotation, "QUOTATION_APPROVED")
        return success_response(
            request,
            code="QUOTATION_APPROVED",
            message=f"Quotation {quotation.quotation_number} approved successfully.",
            data=QuotationSerializer(quotation, context={"compact": False}).data,
            status_code=status.HTTP_200_OK,
        )


class QuotationRejectAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def patch(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)
        serializer = RejectQuotationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")
        try:
            quotation = QuotationService.reject(quotation, reason=reason)
        except InvalidQuotationStatus as exc:
            return error_response(
                request,
                code="INVALID_QUOTATION_STATUS",
                message=str(exc),
                error="Quotation must be 'sent' to reject.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        _log_event(request, quotation, "QUOTATION_REJECTED", after={"reason": reason})
        return success_response(
            request,
            code="QUOTATION_REJECTED",
            message=f"Quotation {quotation.quotation_number} rejected.",
            data=QuotationSerializer(quotation, context={"compact": False}).data,
            status_code=status.HTTP_200_OK,
        )


class QuotationCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def patch(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)
        serializer = CancelQuotationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")
        try:
            quotation = QuotationService.cancel(quotation, reason=reason)
        except InvalidQuotationStatus as exc:
            return error_response(
                request,
                code="INVALID_QUOTATION_STATUS",
                message=str(exc),
                error="This quotation cannot be cancelled from its current status.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        _log_event(request, quotation, "QUOTATION_CANCELLED", after={"reason": reason})
        return success_response(
            request,
            code="QUOTATION_CANCELLED",
            message=f"Quotation {quotation.quotation_number} cancelled.",
            data=QuotationSerializer(quotation, context={"compact": False}).data,
            status_code=status.HTTP_200_OK,
        )


class QuotationReviseAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def post(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk, for_update_check=True)
        serializer = RevisionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["revision_reason"]
        try:
            new_version = QuotationService.create_revision(
                quotation, revision_reason=reason, created_by=request.user
            )
        except QuotationNotLatestVersion as exc:
            return error_response(
                request,
                code="QUOTATION_NOT_LATEST",
                message=str(exc),
                error="Only the latest version can be revised.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except QuotationRevisionNotAllowed as exc:
            return error_response(
                request,
                code="QUOTATION_REVISION_NOT_ALLOWED",
                message=str(exc),
                error="This quotation's status does not support revisions.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        _log_event(
            request, new_version, "QUOTATION_REVISED",
            after={"parent_version": quotation.version, "new_version": new_version.version, "reason": reason},
        )
        return success_response(
            request,
            code="QUOTATION_REVISED",
            message=f"Quotation {new_version.quotation_number} v{new_version.version} created.",
            data=QuotationSerializer(new_version, context={"compact": False}).data,
            status_code=status.HTTP_201_CREATED,
        )


class QuotationConvertToJobCardAPIView(APIView):
    permission_classes = [IsAuthenticatedQuotationAccess]

    def post(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk, for_update_check=True)
        try:
            job_card = QuotationService.convert_to_job_card(quotation)
        except QuotationAlreadyConverted as exc:
            return error_response(
                request,
                code="QUOTATION_ALREADY_CONVERTED",
                message=str(exc),
                error="This quotation has already been converted to a job card.",
                status_code=status.HTTP_409_CONFLICT,
            )
        except QuotationNotLatestVersion as exc:
            return error_response(
                request,
                code="QUOTATION_NOT_LATEST",
                message=str(exc),
                error="Only the latest version can be converted.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidQuotationStatus as exc:
            return error_response(
                request,
                code="INVALID_QUOTATION_STATUS",
                message=str(exc),
                error="Quotation must be 'approved' to convert to a job card.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        _log_event(
            request, quotation, "QUOTATION_CONVERTED",
            after={"job_card_id": str(job_card.id), "jobcard_number": job_card.jobcard_number},
        )
        return success_response(
            request,
            code="QUOTATION_CONVERTED",
            message=f"Job card {job_card.jobcard_number} created from quotation {quotation.quotation_number}.",
            data=JobCardSerializer(job_card, context={"tenant_id": job_card.tenant_id, "compact": False}).data,
            status_code=status.HTTP_201_CREATED,
        )


class QuotationPreviewHtmlAPIView(APIView):
    """GET /api/v1/quotations/{id}/preview-html/ — raw HTML for iframe preview, same template as the PDF."""

    permission_classes = [IsAuthenticatedQuotationAccess]

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)

        from django.http import HttpResponse

        from apps.platform.quotations.pdf_generator import render_quotation_preview_html
        html = render_quotation_preview_html(quotation)
        return HttpResponse(html, content_type="text/html")


class QuotationPdfAPIView(APIView):
    """POST /api/v1/quotations/{id}/generate-pdf/ — generate (or return cached) PDF, return its URL."""

    permission_classes = [IsAuthenticatedQuotationAccess]

    def post(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        quotation = _get_quotation(request, pk)

        force = request.query_params.get("force", "false").lower() in {"true", "1", "yes"}
        already_had_pdf = bool(quotation.pdf_key) and not force

        from apps.platform.quotations.pdf_service import (
            PdfGenerationError,
            PdfNotAvailableError,
            QuotationPdfService,
        )

        try:
            pdf_key = QuotationPdfService.generate_and_store(quotation, force=force)
        except PdfNotAvailableError as exc:
            return error_response(
                request,
                code="PDF_DEPENDENCY_MISSING",
                message=str(exc),
                error="playwright must be installed to generate PDFs.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PdfGenerationError as exc:
            return error_response(
                request,
                code="PDF_GENERATION_FAILED",
                message=str(exc),
                error="An error occurred while generating the quotation PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_url = QuotationPdfService.resolve_url(pdf_key)
        generated = not already_had_pdf
        return success_response(
            request,
            code="PDF_READY",
            message="Quotation PDF is ready.",
            data={"pdf_url": pdf_url, "generated": generated},
            status_code=status.HTTP_200_OK if already_had_pdf else status.HTTP_201_CREATED,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_event(request, quotation: Quotation, action: str, *, after: dict | None = None) -> None:
    try:
        from core.audit.service import log_audit_event
        payload = {"quotation_id": str(quotation.pk), "quotation_number": quotation.quotation_number, "version": quotation.version}
        if after:
            payload.update(after)
        log_audit_event(
            actor_id=str(request.user.pk),
            actor_type="user",
            action=action,
            module="QUOTATION",
            ip_address=_get_client_ip(request),
            method=request.method,
            endpoint=request.path,
            after=payload,
        )
    except Exception:
        pass


def _get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
