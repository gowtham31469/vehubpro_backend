from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.jobcards.models import JobCard
from apps.platform.jobcards.permissions import IsAuthenticatedJobCardAccess
from apps.platform.jobcards.serializers import JobCardSerializer
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
        return Q(status__in=[JobCard.STATUS_DRAFT, JobCard.STATUS_CONFIRMED])
    if t == "in_progress":
        return Q(status__in=[JobCard.STATUS_IN_PROGRESS, JobCard.STATUS_ON_HOLD])
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
            status__in=[JobCard.STATUS_IN_PROGRESS, JobCard.STATUS_ON_HOLD, JobCard.STATUS_CONFIRMED]
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
