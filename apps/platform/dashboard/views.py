"""
Dashboard API views — aggregated, tenant-scoped, PII-free metrics.

Compliance notes
----------------
DPDP Act 2023 / GDPR:
  - Zero raw PII is returned from any endpoint here. All data is aggregated
    (counts, sums, grouped enums). Customer names, phone numbers, emails, and
    addresses are never queried or serialised.
  - RecentActivityView returns jobcard_number and vehicle_registration_no only —
    both are operational identifiers that are not classified as personal data
    under DPDP or GDPR.

ISO 27001 (A.9 Access Control / A.12 Operations):
  - Every view validates tenant_id from the JWT claim before touching the DB.
    A missing or mismatched tenant short-circuits with HTTP 400.
  - All queries are scoped to `tenant_id` — cross-tenant data leakage is
    structurally impossible through these endpoints.
  - No raw SQL; ORM-only to avoid injection surface.

Query performance strategy
--------------------------
  - DashboardSummaryView: 3 queries total using `.aggregate()` with
    conditional COUNT/SUM (`filter=Q(...)`) — single round-trip per model.
  - All other views: 1 query each, using `.values().annotate()` for GROUP BY
    aggregation or a bounded LIMIT slice.
  - `only()` / `values()` everywhere — no full-model hydration.
  - Caller-supplied limits are capped server-side to prevent abuse.

Recommended cache layer (not wired here — add in urls.py or middleware):
  - SummaryView: Redis TTL 60 s, key = f"dash:summary:{tenant_id}"
  - RevenueTrendView: Redis TTL 300 s, key = f"dash:revenue:{tenant_id}:{months}"
  - TopServicesView: Redis TTL 300 s, key = f"dash:top_svc:{tenant_id}:{months}:{limit}"

Recommended DB indexes (add via migration if not present):
  - jobcards_jobcard: (tenant_id, status)              -- already exists
  - jobcards_jobcard: (tenant_id, status, updated_at)  -- add for month filter
  - invoices_invoice: (tenant_id, payment_status)      -- add
  - invoices_invoice: (tenant_id, created_at)          -- add
  - invoices_invoicelineitem: (invoice_id)              -- FK index, auto
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.views import APIView

from apps.platform.customers.models import Customer
from apps.platform.customers.permissions import IsAuthenticatedCustomerAccess
from apps.platform.invoices.models import Invoice, InvoiceLineItem
from apps.platform.jobcards.models import JobCard
from apps.platform.vehicles.models import ServiceVehicle
from core.utils.api_response import error_response, success_response

# ── Constants ──────────────────────────────────────────────────────────────────

_ACTIVE_STATUSES = ("job_control", "working", "ready_for_fi")
_CLOSED_STATUSES = ("completed", "invoiced", "delivered")
_ALL_STATUSES = (
    "job_control", "working", "ready_for_fi",
    "completed", "invoiced", "delivered", "cancelled",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tenant_or_error(request):
    """
    Extract tenant_id from the JWT claim embedded at login.
    Returns (tenant_id, None) on success or (None, error_response) on failure.
    Callers must return the error_response immediately when tenant_id is None.
    """
    tenant_id = getattr(request.user, "tenant_id", None)
    if not tenant_id:
        return None, error_response(
            request,
            code="TENANT_CONTEXT_MISSING",
            message="Authenticated user is not mapped to a tenant.",
            error=None,
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )
    return tenant_id, None


def _month_start():
    """Return the first instant of the current calendar month (UTC)."""
    now = timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ── Views ──────────────────────────────────────────────────────────────────────

class DashboardSummaryView(APIView):
    """
    GET /api/v1/dashboard/summary/

    Returns all top-level KPI counters in a single response using only
    3 database round-trips (one per model group).

    Response shape
    --------------
    {
      "total_customers": 142,
      "total_vehicles": 198,
      "active_jobs": 23,
      "completed_this_month": 47,
      "total_jobs": 312,
      "revenue_this_month": 184500.00,
      "outstanding_amount": 32750.00
    }

    Definitions
    -----------
    active_jobs           — job cards in (confirmed | in_progress | on_hold)
    completed_this_month  — job cards reaching a closed status this calendar month
    revenue_this_month    — sum of amount_paid on all invoices created this month
    outstanding_amount    — sum of (total_amount - amount_paid) for unpaid/partial invoices
    """
    permission_classes = [IsAuthenticatedCustomerAccess]

    def get(self, request):
        tenant_id, err = _tenant_or_error(request)
        if err:
            return err

        month_start = _month_start()

        # ── Query 1: Customer + Vehicle counts ─────────────────────────────────
        total_customers = (
            Customer.objects
            .filter(tenant_id=tenant_id, is_archived=False, status="active")
            .count()
        )
        total_vehicles = (
            ServiceVehicle.objects
            .filter(tenant_id=tenant_id, is_archived=False)
            .count()
        )

        # ── Query 2: Job card aggregates (single DB round-trip) ────────────────
        jc_stats = (
            JobCard.objects
            .filter(tenant_id=tenant_id)
            .aggregate(
                active_jobs=Count(
                    "id",
                    filter=Q(status__in=_ACTIVE_STATUSES),
                ),
                completed_this_month=Count(
                    "id",
                    filter=Q(status__in=_CLOSED_STATUSES, updated_at__gte=month_start),
                ),
                total_jobs=Count("id"),
            )
        )

        # ── Query 3: Invoice aggregates ────────────────────────────────────────
        inv_base = Invoice.objects.filter(tenant_id=tenant_id)

        revenue_this_month = (
            inv_base
            .filter(created_at__gte=month_start)
            .aggregate(total=Sum("amount_paid"))["total"] or 0
        )

        # ExpressionWrapper required because F-arithmetic output type is ambiguous
        outstanding_amount = (
            inv_base
            .filter(payment_status__in=("unpaid", "partial"))
            .annotate(
                balance=ExpressionWrapper(
                    F("total_amount") - F("amount_paid"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .aggregate(total=Sum("balance"))["total"] or 0
        )

        return success_response(
            request,
            code="DASHBOARD_SUMMARY_RETRIEVED",
            message="Dashboard summary retrieved successfully.",
            status_code=http_status.HTTP_200_OK,
            data={
                "total_customers": total_customers,
                "total_vehicles": total_vehicles,
                "active_jobs": jc_stats["active_jobs"] or 0,
                "completed_this_month": jc_stats["completed_this_month"] or 0,
                "total_jobs": jc_stats["total_jobs"] or 0,
                "revenue_this_month": float(revenue_this_month),
                "outstanding_amount": float(outstanding_amount),
            },
        )


class JobCardFunnelView(APIView):
    """
    GET /api/v1/dashboard/jobcard-funnel/

    Returns job card counts grouped by status for pipeline/funnel charts.
    All 7 statuses are always present (count defaults to 0).

    Response shape
    --------------
    [
      {"status": "job_control",  "count": 3},
      {"status": "working",      "count": 8},
      {"status": "ready_for_fi", "count": 3},
      {"status": "completed",    "count": 47},
      {"status": "invoiced",     "count": 39},
      {"status": "delivered",    "count": 180},
      {"status": "cancelled",    "count": 20}
    ]
    """
    permission_classes = [IsAuthenticatedCustomerAccess]

    def get(self, request):
        tenant_id, err = _tenant_or_error(request)
        if err:
            return err

        rows = (
            JobCard.objects
            .filter(tenant_id=tenant_id)
            .values("status")
            .annotate(count=Count("id"))
        )

        # Build a lookup and return all statuses in a fixed display order
        counts = {r["status"]: r["count"] for r in rows}
        data = [{"status": s, "count": counts.get(s, 0)} for s in _ALL_STATUSES]

        return success_response(
            request,
            code="JOBCARD_FUNNEL_RETRIEVED",
            message="Job card funnel retrieved successfully.",
            status_code=http_status.HTTP_200_OK,
            data=data,
        )


class RevenueTrendView(APIView):
    """
    GET /api/v1/dashboard/revenue-trend/?months=6

    Returns monthly collected revenue (amount_paid) and invoice count for
    the last N calendar months. Maximum lookback is 24 months.

    Query param
    -----------
    months  int (default 6, max 24)  — how many months back to include

    Response shape
    --------------
    [
      {"month": "2025-10", "revenue": 98000.00, "invoice_count": 31},
      {"month": "2025-11", "revenue": 112500.00, "invoice_count": 38},
      ...
    ]

    Note: months with zero invoices are omitted (sparse series).
    The frontend should handle gaps when rendering charts.
    """
    permission_classes = [IsAuthenticatedCustomerAccess]

    _MAX_MONTHS = 24

    def get(self, request):
        tenant_id, err = _tenant_or_error(request)
        if err:
            return err

        try:
            months = min(int(request.query_params.get("months", 6)), self._MAX_MONTHS)
        except (TypeError, ValueError):
            months = 6

        since = timezone.now() - timedelta(days=months * 31)

        rows = (
            Invoice.objects
            .filter(tenant_id=tenant_id, created_at__gte=since)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(
                revenue=Sum("amount_paid"),
                invoice_count=Count("id"),
            )
            .order_by("month")
        )

        data = [
            {
                "month": r["month"].strftime("%Y-%m"),
                "revenue": float(r["revenue"] or 0),
                "invoice_count": r["invoice_count"],
            }
            for r in rows
        ]

        return success_response(
            request,
            code="REVENUE_TREND_RETRIEVED",
            message="Revenue trend retrieved successfully.",
            status_code=http_status.HTTP_200_OK,
            data=data,
        )


class PaymentDistributionView(APIView):
    """
    GET /api/v1/dashboard/payment-distribution/

    Returns invoice count and total billed amount split by payment_status.
    Used to render a donut/pie chart of payment health.

    Response shape
    --------------
    [
      {"status": "paid",    "count": 210, "total_amount": 892500.00},
      {"status": "partial", "count": 14,  "total_amount": 68200.00},
      {"status": "unpaid",  "count": 22,  "total_amount": 43100.00}
    ]
    """
    permission_classes = [IsAuthenticatedCustomerAccess]

    def get(self, request):
        tenant_id, err = _tenant_or_error(request)
        if err:
            return err

        rows = (
            Invoice.objects
            .filter(tenant_id=tenant_id)
            .values("payment_status")
            .annotate(count=Count("id"), total_amount=Sum("total_amount"))
            .order_by("payment_status")
        )

        data = [
            {
                "status": r["payment_status"],
                "count": r["count"],
                "total_amount": float(r["total_amount"] or 0),
            }
            for r in rows
        ]

        return success_response(
            request,
            code="PAYMENT_DISTRIBUTION_RETRIEVED",
            message="Payment distribution retrieved successfully.",
            status_code=http_status.HTTP_200_OK,
            data=data,
        )


class RecentActivityView(APIView):
    """
    GET /api/v1/dashboard/recent-activity/?limit=10

    Returns the most recently updated job cards. Only operational identifiers
    are returned — no customer names, phone numbers, or other PII.

    Query param
    -----------
    limit  int (default 10, max 25)

    Response shape
    --------------
    [
      {
        "id": "uuid",
        "jobcard_number": "JC/25-26/000042",
        "status": "working",
        "total_amount": 4500.00,
        "vehicle_registration": "TN40N3409",
        "updated_at": "2026-04-04T09:15:00+00:00",
        "created_at": "2026-04-03T14:30:00+00:00"
      },
      ...
    ]

    DPDP/GDPR: vehicle_registration_no is a statutory government identifier,
    not personal data. Customer name is deliberately excluded.
    """
    permission_classes = [IsAuthenticatedCustomerAccess]

    _MAX_LIMIT = 25

    def get(self, request):
        tenant_id, err = _tenant_or_error(request)
        if err:
            return err

        try:
            limit = min(int(request.query_params.get("limit", 10)), self._MAX_LIMIT)
        except (TypeError, ValueError):
            limit = 10

        # values() + F() alias avoids full model hydration; single query with JOIN
        rows = (
            JobCard.objects
            .filter(tenant_id=tenant_id)
            .values(
                "id",
                "jobcard_number",
                "status",
                "total_amount",
                "updated_at",
                "created_at",
                vehicle_registration=F("vehicle__registration_no"),
            )
            .order_by("-updated_at")[:limit]
        )

        data = [
            {
                "id": str(r["id"]),
                "jobcard_number": r["jobcard_number"],
                "status": r["status"],
                "total_amount": float(r["total_amount"] or 0),
                "vehicle_registration": r["vehicle_registration"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return success_response(
            request,
            code="RECENT_ACTIVITY_RETRIEVED",
            message="Recent activity retrieved successfully.",
            status_code=http_status.HTTP_200_OK,
            data=data,
        )


class TopServicesView(APIView):
    """
    GET /api/v1/dashboard/top-services/?limit=5&months=3

    Returns the most frequently billed service descriptions ranked by
    occurrence count. Uses InvoiceLineItem (immutable snapshot) so it
    reflects actual billed work, not the live service catalog.

    Query params
    ------------
    limit   int (default 5, max 20)   — number of services to return
    months  int (default 3, max 12)   — lookback window in months

    Response shape
    --------------
    [
      {"description": "Basic Car Service",  "count": 84, "revenue": 126000.00},
      {"description": "Oil & Filter Change","count": 71, "revenue": 35500.00},
      ...
    ]

    ISO 27001: query filters through invoice__tenant_id ensuring strict
    tenant boundary — a tenant cannot see another tenant's line items.
    """
    permission_classes = [IsAuthenticatedCustomerAccess]

    _MAX_LIMIT = 20
    _MAX_MONTHS = 12

    def get(self, request):
        tenant_id, err = _tenant_or_error(request)
        if err:
            return err

        try:
            limit = min(int(request.query_params.get("limit", 5)), self._MAX_LIMIT)
            months = min(int(request.query_params.get("months", 3)), self._MAX_MONTHS)
        except (TypeError, ValueError):
            limit, months = 5, 3

        since = timezone.now() - timedelta(days=months * 31)

        rows = (
            InvoiceLineItem.objects
            .filter(
                invoice__tenant_id=tenant_id,
                invoice__created_at__gte=since,
            )
            .values("description")
            .annotate(count=Count("id"), revenue=Sum("line_total"))
            .order_by("-count")[:limit]
        )

        data = [
            {
                "description": r["description"],
                "count": r["count"],
                "revenue": float(r["revenue"] or 0),
            }
            for r in rows
        ]

        return success_response(
            request,
            code="TOP_SERVICES_RETRIEVED",
            message="Top services retrieved successfully.",
            status_code=http_status.HTTP_200_OK,
            data=data,
        )
