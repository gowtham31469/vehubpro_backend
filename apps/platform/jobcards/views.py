from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.jobcards.models import JobCard
from apps.platform.jobcards.permissions import IsAuthenticatedJobCardAccess
from apps.platform.jobcards.serializers import JobCardSerializer
from apps.platform.jobcards.pdf_service import (
    JobCardPdfService,
    PdfGenerationError,
    PdfNotAvailableError,
)
from core.utils.api_response import error_response, success_response
from core.utils.pagination import StandardResultsSetPagination


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


def _tab_q(tab: str) -> Q:
    t = (tab or "all").strip().lower()
    if t == "all" or not t:
        return Q()
    if t == "open":
        return Q(status=JobCard.STATUS_JOB_CONTROL)
    if t == "in_progress":
        return Q(status__in=[JobCard.STATUS_WORKING, JobCard.STATUS_READY_FOR_FI])
    if t == "completed":
        return Q(status=JobCard.STATUS_COMPLETED)
    if t == "delivered":
        return Q(status__in=[JobCard.STATUS_DELIVERED, JobCard.STATUS_INVOICED])
    return Q()


class JobCardListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedJobCardAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        tab = request.query_params.get("tab", "all")
        search = (request.query_params.get("search") or "").strip()

        queryset = (
            JobCard.objects.filter(tenant_id=tenant_id)
            .select_related("customer", "vehicle", "vehicle__brand", "vehicle__vehicle_model", "assigned_technician")
            .prefetch_related("line_items")
            .filter(_tab_q(tab))
            .order_by("-created_at", "-jobcard_number")
        )
        if search:
            queryset = queryset.filter(
                Q(jobcard_number__icontains=search)
                | Q(customer__full_name__icontains=search)
                | Q(vehicle__registration_no__icontains=search)
            )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = JobCardSerializer(
            page,
            many=True,
            context={"request": request, "tenant_id": tenant_id, "compact": True},
        )
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Job cards retrieved successfully.",
            data={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data,
            },
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("jobcard_number", None)
        serializer = JobCardSerializer(
            data=payload, context={"request": request, "tenant_id": tenant_id, "compact": False}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="JOB_CARD_CREATED",
            message="Job card created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class JobCardDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedJobCardAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(
            JobCard.objects.select_related(
                "customer", "vehicle", "vehicle__brand", "vehicle__vehicle_model", "assigned_technician"
            )
            .prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        serializer = JobCardSerializer(
            self.get_object(request, pk), context={"request": request, "tenant_id": tenant_id, "compact": False}
        )
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Job card retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        if instance.status == JobCard.STATUS_INVOICED:
            return error_response(
                request,
                code="JOB_CARD_LOCKED",
                message="This job card is already invoiced and cannot be modified.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("jobcard_number", None)
        serializer = JobCardSerializer(
            instance, data=payload, context={"request": request, "tenant_id": tenant_id}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="JOB_CARD_UPDATED",
            message="Job card updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        if instance.status == JobCard.STATUS_INVOICED:
            return error_response(
                request,
                code="JOB_CARD_LOCKED",
                message="This job card is already invoiced and cannot be modified.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("jobcard_number", None)
        serializer = JobCardSerializer(
            instance, data=payload, partial=True, context={"request": request, "tenant_id": tenant_id}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="JOB_CARD_UPDATED",
            message="Job card updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        self.get_object(request, pk).delete()
        return success_response(
            request,
            code="JOB_CARD_DELETED",
            message="Job card deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class JobCardStatsAPIView(APIView):
    permission_classes = [IsAuthenticatedJobCardAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        today = timezone.now().date()
        qs = JobCard.objects.filter(tenant_id=tenant_id)

        total_active = qs.exclude(status__in=[JobCard.STATUS_DELIVERED, JobCard.STATUS_CANCELLED]).count()
        in_workshop = qs.filter(
            status__in=[JobCard.STATUS_WORKING, JobCard.STATUS_READY_FOR_FI]
        ).count()
        completed_today = qs.filter(status=JobCard.STATUS_COMPLETED, updated_at__date=today).count()
        revenue = qs.exclude(status=JobCard.STATUS_CANCELLED).aggregate(s=Sum("total_amount"))["s"]
        revenue_estimated = revenue if revenue is not None else 0

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Job card stats retrieved successfully.",
            data={
                "total_active": total_active,
                "in_workshop": in_workshop,
                "completed_today": completed_today,
                "revenue_estimated": str(revenue_estimated),
            },
            status_code=status.HTTP_200_OK,
        )


class JobCardPdfAPIView(APIView):
    """
    POST /api/v1/job-cards/{id}/generate-pdf/

    Generates an operational PDF for a job card and returns its pre-signed URL.
    """

    permission_classes = [IsAuthenticatedJobCardAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        job_card = get_object_or_404(
            JobCard.objects.select_related(
                "customer", "vehicle", "vehicle__brand", "vehicle__vehicle_model", "tenant"
            ).prefetch_related("line_items"),
            pk=pk,
            tenant_id=tenant_id,
        )

        if job_card.status == JobCard.STATUS_JOB_CONTROL:
            return error_response(
                request,
                code="PDF_NOT_ALLOWED",
                message="Job card PDF is not available while the job card is in 'Job Control' status.",
                error="Move the job card to Working or beyond before downloading.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Audit — generating the PDF may decrypt PII (name, phone) at render time
        _log_pii_access(request, job_card)

        try:
            pdf_key = JobCardPdfService.generate_and_store(job_card, force=True)
            pdf_url = JobCardPdfService.resolve_url(pdf_key)
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
                error="An error occurred while generating the job card PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return success_response(
            request,
            code="PDF_READY",
            message="Job card PDF is ready.",
            data={"pdf_url": pdf_url},
            status_code=status.HTTP_200_OK,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_pii_access(request, job_card: JobCard) -> None:
    try:
        from core.audit.service import log_audit_event
        log_audit_event(
            actor_id=str(request.user.pk),
            actor_type="user",
            action="PII_ACCESS",
            module="JOB_CARD",
            ip_address=_get_client_ip(request),
            method=request.method,
            endpoint=request.path,
            after={"job_card_id": str(job_card.pk), "jobcard_number": job_card.jobcard_number},
        )
    except Exception:
        pass


def _get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
