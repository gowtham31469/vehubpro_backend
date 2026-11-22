"""
Vendor views.

Endpoints
---------
GET/POST  /api/v1/vendors/                     List / create vendors.
GET/PATCH /api/v1/vendors/{id}/                 Vendor detail / edit / archive-reactivate.
GET       /api/v1/vendors/insights/             Accounts-payable analytics summary.
GET/POST  /api/v1/vendors/bills/                List / create vendor bills.
GET       /api/v1/vendors/bills/{id}/           Vendor bill detail.
PATCH     /api/v1/vendors/bills/{id}/cancel/    Cancel a vendor bill.
GET/POST  /api/v1/vendors/payments/             List / create vendor payments.
PATCH     /api/v1/vendors/payments/{id}/void/   Void a vendor payment.

All views enforce tenant isolation: only rows belonging to
request.user.tenant_id are ever returned or mutated.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.platform.vendors.models import Vendor, VendorBill, VendorCategory, VendorPayment
from apps.platform.vendors.permissions import IsAuthenticatedVendorAccess
from apps.platform.vendors.serializers import (
    CancelVendorBillSerializer,
    GenerateVendorBillSerializer,
    RecordVendorPaymentSerializer,
    VendorBillDetailSerializer,
    VendorBillListSerializer,
    VendorCategorySerializer,
    VendorDetailSerializer,
    VendorListSerializer,
    VendorPaymentSerializer,
    VendorWriteSerializer,
    VoidVendorPaymentSerializer,
    vendor_category_integrity_errors,
)
from apps.platform.vendors.service import (
    InvalidVendorBillReference,
    OverPaymentError,
    VendorBillAlreadyCancelled,
    VendorBillHasPayments,
    VendorBillService,
    VendorPaymentAlreadyVoided,
    VendorPaymentService,
)
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


def _get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _log_vendor_event(request, obj, action: str) -> None:
    """Swallowed on failure so it never breaks the response."""
    try:
        from core.audit.service import log_audit_event
        log_audit_event(
            actor_id=str(request.user.pk),
            actor_type="user",
            action=action,
            module="VENDOR",
            ip_address=_get_client_ip(request),
            method=request.method,
            endpoint=request.path,
            after={"id": str(obj.pk)},
        )
    except Exception:
        pass


# ── Vendor Categories (tenant-curated master, managed in Configuration) ──────

def _is_archive_flag(request) -> bool:
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


def _is_active_flag(request):
    value = request.query_params.get("is_active")
    if value is None:
        return None
    return str(value).strip().lower() in {"true", "1", "yes"}


class VendorCategoryListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = VendorCategory.objects.filter(
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
            message="Vendor categories retrieved successfully.",
            data=build_paginated_data(request, queryset, VendorCategorySerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VendorCategorySerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request, code="INTEGRITY_ERROR", message="Could not create vendor category.",
                error=vendor_category_integrity_errors(exc), status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request, code="VENDOR_CATEGORY_CREATED", message="Vendor category created successfully.",
            data=serializer.data, status_code=status.HTTP_201_CREATED,
        )


class VendorCategoryDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(VendorCategory, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = VendorCategorySerializer(self.get_object(request, pk))
        return success_response(
            request, code="DATA_RETRIEVED", message="Vendor category retrieved successfully.",
            data=serializer.data, status_code=status.HTTP_200_OK,
        )

    def _update(self, request, pk, *, partial):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VendorCategorySerializer(instance, data=payload, partial=partial, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as exc:
            return error_response(
                request, code="INTEGRITY_ERROR", message="Could not update vendor category.",
                error=vendor_category_integrity_errors(exc), status_code=status.HTTP_409_CONFLICT,
            )
        return success_response(
            request, code="VENDOR_CATEGORY_UPDATED", message="Vendor category updated successfully.",
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
        category = get_object_or_404(VendorCategory, pk=pk, tenant_id=tenant_id, is_archived=False)
        # Vendor.category is a text snapshot, not an FK — no dependents to
        # unlink, unlike LabourCategory's ServiceItem case.
        category.archive()
        return success_response(
            request, code="VENDOR_CATEGORY_DELETED", message="Vendor category archived successfully.",
            data={}, status_code=status.HTTP_200_OK,
        )


# ── Vendor Insights (accounts-payable analytics) ─────────────────────────────

class VendorInsightsAPIView(APIView):
    """
    GET /api/v1/vendors/insights/?months=6&limit=8

    Bundles everything the Vendor Insights page needs in one round trip:
    summary KPIs, payment-status breakdown, a monthly spend trend, the
    top vendors by outstanding balance, and a spend-by-category breakdown.
    All queries are tenant-scoped aggregates — no per-vendor N+1 queries
    (outstanding balance is computed batched across all vendors in two
    GROUP BY queries, then merged in Python, mirroring
    service.vendor_outstanding_balance()'s math without looping per vendor).
    """

    permission_classes = [IsAuthenticatedVendorAccess]
    _MAX_MONTHS = 24
    _MAX_LIMIT = 20

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        try:
            months = min(int(request.query_params.get("months", 6)), self._MAX_MONTHS)
        except (TypeError, ValueError):
            months = 6
        try:
            limit = min(int(request.query_params.get("limit", 8)), self._MAX_LIMIT)
        except (TypeError, ValueError):
            limit = 8

        due_expr = ExpressionWrapper(
            F("net_payable_amount") - F("amount_paid"), output_field=DecimalField(max_digits=14, decimal_places=2)
        )

        issued_bills = VendorBill.objects.filter(tenant_id=tenant_id, status=VendorBill.STATUS_ISSUED)

        # ── Per-vendor outstanding (two batched GROUP BYs, merged in Python —
        #     on-account payments aren't tied to any one bill, so they can't
        #     be summed in the same query as the bills themselves). ─────────
        bills_by_vendor = issued_bills.values("vendor_id", "vendor__name").annotate(due=Sum(due_expr))
        on_account_by_vendor = {
            row["vendor_id"]: row["total"]
            for row in VendorPayment.objects.filter(
                tenant_id=tenant_id, vendor_bill__isnull=True, is_voided=False
            ).values("vendor_id").annotate(total=Sum("amount"))
        }
        top_vendors = []
        total_outstanding = 0.0
        for row in bills_by_vendor:
            due = float(row["due"] or 0)
            on_account = float(on_account_by_vendor.get(row["vendor_id"]) or 0)
            outstanding = due - on_account
            total_outstanding += outstanding
            if outstanding > 0:
                top_vendors.append({
                    "vendor_id": str(row["vendor_id"]), "vendor_name": row["vendor__name"], "outstanding": outstanding,
                })
        top_vendors.sort(key=lambda r: r["outstanding"], reverse=True)
        top_vendors = top_vendors[:limit]

        # ── Overdue (issued, past due date, not fully paid). ────────────────
        overdue_agg = issued_bills.filter(
            due_date__isnull=False, due_date__lt=timezone.now().date(),
        ).exclude(payment_status=VendorBill.PAYMENT_STATUS_PAID).aggregate(
            overdue_count=Count("id"), overdue_amount=Sum(due_expr),
        )

        # ── Payment-status breakdown (backfilled so all 3 statuses always
        #     appear, even at 0 — same convention as JobCardFunnelView). ────
        by_status = {
            row["payment_status"]: row
            for row in issued_bills.values("payment_status").annotate(count=Count("id"), total=Sum("net_payable_amount"))
        }
        payment_status_breakdown = [
            {
                "status": key,
                "count": (by_status.get(key) or {}).get("count", 0),
                "total": float((by_status.get(key) or {}).get("total") or 0),
            }
            for key, _label in VendorBill.PAYMENT_STATUS_CHOICES
        ]

        # ── Monthly spend trend (by the bill's own date, not when it was
        #     entered — sparse months are omitted, same convention as
        #     dashboard.RevenueTrendView). ────────────────────────────────────
        since = timezone.now().date() - timedelta(days=months * 31)
        trend_rows = (
            issued_bills.filter(bill_date__gte=since)
            .annotate(month=TruncMonth("bill_date"))
            .values("month")
            .annotate(total=Sum("net_payable_amount"), count=Count("id"))
            .order_by("month")
        )
        monthly_trend = [
            {"month": r["month"].strftime("%Y-%m"), "total": float(r["total"] or 0), "count": r["count"]}
            for r in trend_rows
        ]

        # ── Spend by vendor category. ────────────────────────────────────────
        category_rows = (
            issued_bills.values("vendor__category")
            .annotate(total=Sum("net_payable_amount"), count=Count("id"))
            .order_by("-total")
        )
        category_breakdown = [
            {"category": r["vendor__category"] or "Other", "total": float(r["total"] or 0), "count": r["count"]}
            for r in category_rows
        ][:10]

        data = {
            "summary": {
                "total_vendors": Vendor.objects.filter(tenant_id=tenant_id, is_archived=False).count(),
                "total_outstanding": total_outstanding,
                "total_bills_issued": issued_bills.count(),
                "overdue_count": overdue_agg["overdue_count"] or 0,
                "overdue_amount": float(overdue_agg["overdue_amount"] or 0),
            },
            "payment_status_breakdown": payment_status_breakdown,
            "monthly_trend": monthly_trend,
            "top_vendors": top_vendors,
            "category_breakdown": category_breakdown,
        }

        return success_response(
            request, code="DATA_RETRIEVED", message="Vendor insights retrieved successfully.",
            data=data, status_code=status.HTTP_200_OK,
        )


# ── Vendors ───────────────────────────────────────────────────────────────────

class VendorListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = Vendor.objects.filter(tenant_id=tenant_id)

        archived = request.query_params.get("archived", "").strip().lower()
        if archived in {"true", "1", "yes"}:
            queryset = queryset.filter(is_archived=True)
        elif archived in {"false", "0", "no"}:
            queryset = queryset.filter(is_archived=False)

        category = request.query_params.get("category", "").strip()
        if category:
            queryset = queryset.filter(category=category)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(gstin__icontains=search) | Q(phone__icontains=search)
            )

        return success_response(
            request, code="DATA_RETRIEVED", message="Vendors retrieved successfully.",
            data=build_paginated_data(request, queryset, VendorListSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        serializer = VendorWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor = serializer.save(tenant_id=tenant_id, created_by=request.user)

        _log_vendor_event(request, vendor, "VENDOR_CREATED")
        return success_response(
            request, code="VENDOR_CREATED", message="Vendor created successfully.",
            data=VendorDetailSerializer(vendor).data, status_code=status.HTTP_201_CREATED,
        )


class VendorDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(Vendor, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        vendor = self.get_object(request, pk)
        return success_response(
            request, code="DATA_RETRIEVED", message="Vendor retrieved successfully.",
            data=VendorDetailSerializer(vendor).data, status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        vendor = self.get_object(request, pk)

        archive_action = request.data.get("archive_action")
        if archive_action == "archive":
            vendor.archive()
            _log_vendor_event(request, vendor, "VENDOR_ARCHIVED")
        elif archive_action == "reactivate":
            vendor.is_archived = False
            vendor.archived_at = None
            vendor.save(update_fields=["is_archived", "archived_at", "updated_at"])
            _log_vendor_event(request, vendor, "VENDOR_REACTIVATED")
        else:
            serializer = VendorWriteSerializer(vendor, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            vendor = serializer.save()
            _log_vendor_event(request, vendor, "VENDOR_UPDATED")

        return success_response(
            request, code="VENDOR_UPDATED", message="Vendor updated successfully.",
            data=VendorDetailSerializer(vendor).data, status_code=status.HTTP_200_OK,
        )


# ── Vendor Bills ──────────────────────────────────────────────────────────────

class VendorBillListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = VendorBill.objects.filter(tenant_id=tenant_id).select_related("vendor")

        vendor_id = request.query_params.get("vendor_id", "").strip()
        if vendor_id:
            queryset = queryset.filter(vendor_id=vendor_id)

        bill_status = request.query_params.get("status", "").strip()
        if bill_status in {VendorBill.STATUS_ISSUED, VendorBill.STATUS_CANCELLED}:
            queryset = queryset.filter(status=bill_status)

        payment_status = request.query_params.get("payment_status", "").strip()
        if payment_status in dict(VendorBill.PAYMENT_STATUS_CHOICES):
            queryset = queryset.filter(payment_status=payment_status)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(bill_number__icontains=search)
                | Q(vendor_bill_reference__icontains=search)
                | Q(vendor__name__icontains=search)
            )

        date_from = request.query_params.get("date_from", "").strip()
        if date_from:
            queryset = queryset.filter(bill_date__gte=date_from)
        date_to = request.query_params.get("date_to", "").strip()
        if date_to:
            queryset = queryset.filter(bill_date__lte=date_to)

        return success_response(
            request, code="DATA_RETRIEVED", message="Vendor bills retrieved successfully.",
            data=build_paginated_data(request, queryset, VendorBillListSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        serializer = GenerateVendorBillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        vendor = get_object_or_404(Vendor, pk=vd["vendor_id"], tenant_id=tenant_id)

        bill = VendorBillService.generate(
            vendor,
            created_by=request.user,
            bill_date=vd["bill_date"],
            due_date=vd.get("due_date"),
            vendor_bill_reference=vd.get("vendor_bill_reference", ""),
            description=vd.get("description", ""),
            subtotal=vd["subtotal"],
            gst_percentage=vd.get("gst_percentage", 0),
            is_interstate=vd.get("is_interstate", False),
            tds_percentage=vd.get("tds_percentage", 0),
            attachment_file=vd.get("attachment"),
        )

        _log_vendor_event(request, bill, "VENDOR_BILL_CREATED")
        return success_response(
            request, code="VENDOR_BILL_CREATED", message="Vendor bill created successfully.",
            data=VendorBillDetailSerializer(bill).data, status_code=status.HTTP_201_CREATED,
        )


class VendorBillDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        bill = get_object_or_404(
            VendorBill.objects.select_related("vendor").prefetch_related("payments"),
            pk=pk, tenant_id=tenant_id,
        )
        return success_response(
            request, code="DATA_RETRIEVED", message="Vendor bill retrieved successfully.",
            data=VendorBillDetailSerializer(bill).data, status_code=status.HTTP_200_OK,
        )


class VendorBillCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        bill = get_object_or_404(VendorBill, pk=pk, tenant_id=tenant_id)
        serializer = CancelVendorBillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            bill = VendorBillService.cancel(
                bill, cancelled_by=request.user, reason=serializer.validated_data.get("reason", "")
            )
        except VendorBillAlreadyCancelled as exc:
            return error_response(
                request, code="VENDOR_BILL_ALREADY_CANCELLED", message=str(exc),
                error="This bill has already been cancelled.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        except VendorBillHasPayments as exc:
            return error_response(
                request, code="VENDOR_BILL_HAS_PAYMENTS", message=str(exc),
                error="This bill has payments recorded against it and cannot be cancelled.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_vendor_event(request, bill, "VENDOR_BILL_CANCELLED")
        bill = VendorBill.objects.select_related("vendor").prefetch_related("payments").get(pk=bill.pk)
        return success_response(
            request, code="VENDOR_BILL_CANCELLED", message=f"Bill {bill.bill_number} cancelled successfully.",
            data=VendorBillDetailSerializer(bill).data, status_code=status.HTTP_200_OK,
        )


# ── Vendor Payments ───────────────────────────────────────────────────────────

class VendorPaymentListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = VendorPayment.objects.filter(tenant_id=tenant_id).select_related("vendor", "vendor_bill")

        vendor_id = request.query_params.get("vendor_id", "").strip()
        if vendor_id:
            queryset = queryset.filter(vendor_id=vendor_id)

        vendor_bill_id = request.query_params.get("vendor_bill_id", "").strip()
        if vendor_bill_id:
            queryset = queryset.filter(vendor_bill_id=vendor_bill_id)

        payment_mode = request.query_params.get("payment_mode", "").strip()
        if payment_mode in dict(VendorPayment.PAYMENT_MODE_CHOICES):
            queryset = queryset.filter(payment_mode=payment_mode)

        date_from = request.query_params.get("date_from", "").strip()
        if date_from:
            queryset = queryset.filter(payment_date__gte=date_from)
        date_to = request.query_params.get("date_to", "").strip()
        if date_to:
            queryset = queryset.filter(payment_date__lte=date_to)

        return success_response(
            request, code="DATA_RETRIEVED", message="Vendor payments retrieved successfully.",
            data=build_paginated_data(request, queryset, VendorPaymentSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        serializer = RecordVendorPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        vendor = get_object_or_404(Vendor, pk=vd["vendor_id"], tenant_id=tenant_id)
        vendor_bill = None
        if vd.get("vendor_bill_id"):
            vendor_bill = get_object_or_404(VendorBill, pk=vd["vendor_bill_id"], tenant_id=tenant_id)

        try:
            payment = VendorPaymentService.record(
                vendor,
                amount=vd["amount"],
                payment_mode=vd["payment_mode"],
                payment_date=vd["payment_date"],
                recorded_by=request.user,
                vendor_bill=vendor_bill,
                payment_reference=vd.get("payment_reference", ""),
                notes=vd.get("notes", ""),
            )
        except InvalidVendorBillReference as exc:
            return error_response(
                request, code="INVALID_VENDOR_BILL", message=str(exc),
                error=str(exc), status_code=status.HTTP_400_BAD_REQUEST,
            )
        except OverPaymentError as exc:
            return error_response(
                request, code="OVER_PAYMENT", message=str(exc),
                error=str(exc), status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_vendor_event(request, payment, "VENDOR_PAYMENT_RECORDED")
        return success_response(
            request, code="VENDOR_PAYMENT_RECORDED", message="Payment recorded successfully.",
            data=VendorPaymentSerializer(payment).data, status_code=status.HTTP_201_CREATED,
        )


class VendorPaymentVoidAPIView(APIView):
    permission_classes = [IsAuthenticatedVendorAccess]

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        payment = get_object_or_404(VendorPayment, pk=pk, tenant_id=tenant_id)
        serializer = VoidVendorPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment = VendorPaymentService.void(
                payment, voided_by=request.user, reason=serializer.validated_data.get("reason", "")
            )
        except VendorPaymentAlreadyVoided as exc:
            return error_response(
                request, code="VENDOR_PAYMENT_ALREADY_VOIDED", message=str(exc),
                error="This payment has already been voided.", status_code=status.HTTP_400_BAD_REQUEST,
            )

        _log_vendor_event(request, payment, "VENDOR_PAYMENT_VOIDED")
        return success_response(
            request, code="VENDOR_PAYMENT_VOIDED", message="Payment voided successfully.",
            data=VendorPaymentSerializer(payment).data, status_code=status.HTTP_200_OK,
        )
