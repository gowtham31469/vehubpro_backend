from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.platform.dealer_sales.models import (
    VehicleAcquisition,
    VehicleBooking,
    VehicleDocument,
    VehicleOwnershipRecord,
    VehiclePriceHistory,
    VehicleReservation,
    VehicleSale,
    VehicleSaleInvoice,
    VehicleSaleQuotation,
    VehicleWorkExpense,
)
from apps.platform.dealer_sales.permissions import IsAuthenticatedDealerSalesAccess
from apps.platform.dealer_sales.serializers import (
    BookingCreateInputSerializer,
    DeliveryCreateInputSerializer,
    InvoiceCreateInputSerializer,
    InvoicePaymentCreateInputSerializer,
    NegotiationCreateInputSerializer,
    QuotationCreateInputSerializer,
    ReasonInputSerializer,
    ReservationCreateInputSerializer,
    SaleCreateInputSerializer,
    SettlementCreateInputSerializer,
    SettlementMarkPaidInputSerializer,
    VehicleAcquisitionSerializer,
    VehicleBookingSerializer,
    VehicleDeliverySerializer,
    VehicleDocumentSerializer,
    VehicleNegotiationSerializer,
    VehicleOwnershipRecordSerializer,
    VehiclePriceHistorySerializer,
    VehicleReservationSerializer,
    VehicleSaleInvoiceSerializer,
    VehicleSaleQuotationSerializer,
    VehicleSalesReportRowSerializer,
    VehicleSaleSerializer,
    VehicleSettlementSerializer,
    VehicleTimelineEventSerializer,
    VehicleWorkExpenseSerializer,
)
from apps.platform.dealer_sales.services import (
    DealerSalesError,
    accept_quotation,
    add_negotiation_round,
    cancel_booking,
    cancel_quotation,
    cancel_reservation,
    cancel_sale,
    compute_portfolio_profitability_insights,
    compute_profitability,
    compute_sale_profit,
    confirm_sale,
    create_booking,
    create_delivery,
    create_quotation,
    create_reservation,
    create_settlement,
    generate_sale_invoice,
    mark_settlement_paid,
    record_sale_invoice_payment,
    record_vehicle_timeline_event,
    reject_quotation,
    sales_report_queryset,
    send_quotation,
)
from apps.platform.portfolio.models import InventoryVehicle
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _resolve_tenant_object(request, model, pk, *, not_found_code, not_found_message):
    tenant_id = getattr(request.user, "tenant_id", None)
    if not tenant_id:
        return None, error_response(
            request,
            code="TENANT_CONTEXT_MISSING",
            message="Authenticated user is not mapped to a tenant.",
            error="Tenant association is required for this endpoint.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    instance = model.objects.filter(id=pk, tenant_id=tenant_id).first()
    if instance is None:
        return None, error_response(
            request,
            code=not_found_code,
            message=not_found_message,
            error=not_found_message,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return instance, None


def _dealer_sales_error_response(request, exc: DealerSalesError):
    return error_response(
        request,
        code="INVALID_STATE_TRANSITION",
        message=str(exc),
        error=str(exc),
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _resolve_vehicle(request, vehicle_id):
    tenant_id = getattr(request.user, "tenant_id", None)
    if not tenant_id:
        return None, error_response(
            request,
            code="TENANT_CONTEXT_MISSING",
            message="Authenticated user is not mapped to a tenant.",
            error="Tenant association is required for this endpoint.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    vehicle = InventoryVehicle.objects.filter(id=vehicle_id, tenant_id=tenant_id, is_archived=False).first()
    if vehicle is None:
        return None, error_response(
            request,
            code="VEHICLE_NOT_FOUND",
            message="Vehicle not found.",
            error="Vehicle not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return vehicle, None


class VehicleAcquisitionDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        acquisition = VehicleAcquisition.objects.filter(vehicle=vehicle, is_archived=False).first()
        data = VehicleAcquisitionSerializer(acquisition).data if acquisition else None
        return success_response(
            request, code="DATA_RETRIEVED", message="Acquisition retrieved successfully.",
            data=data, status_code=status.HTTP_200_OK,
        )

    def put(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        instance = VehicleAcquisition.objects.filter(vehicle=vehicle, is_archived=False).first()
        is_create = instance is None
        serializer = VehicleAcquisitionSerializer(
            instance, data=request.data, partial=not is_create, context={"vehicle": vehicle}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=vehicle.tenant_id, vehicle=vehicle, created_by=request.user)

        record_vehicle_timeline_event(
            vehicle=vehicle,
            category="acquisition",
            title="Acquisition recorded" if is_create else "Acquisition updated",
            description=(
                f"Purchase price ₹{serializer.instance.purchase_price:,.2f}"
                if vehicle.inventory_type == InventoryVehicle.INVENTORY_TYPE_OWNED and serializer.instance.purchase_price
                else f"Owner expected price ₹{serializer.instance.owner_expected_price:,.2f}"
                if serializer.instance.owner_expected_price else ""
            ),
            actor=request.user,
        )
        return success_response(
            request,
            code="ACQUISITION_SAVED",
            message="Acquisition saved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class VehicleOwnershipRecordListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        records = VehicleOwnershipRecord.objects.filter(vehicle=vehicle)
        return success_response(
            request, code="DATA_RETRIEVED", message="Ownership history retrieved successfully.",
            data=VehicleOwnershipRecordSerializer(records, many=True).data, status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = VehicleOwnershipRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant_id=vehicle.tenant_id, vehicle=vehicle, created_by=request.user)

        record_vehicle_timeline_event(
            vehicle=vehicle,
            category="ownership",
            title=f"Ownership record added — {instance.get_owner_type_display()}",
            description=instance.owner_name or "",
            actor=request.user,
        )
        return success_response(
            request, code="OWNERSHIP_RECORD_CREATED", message="Ownership record created successfully.",
            data=serializer.data, status_code=status.HTTP_201_CREATED,
        )


class VehicleWorkExpenseListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehicleWorkExpense.objects.filter(vehicle=vehicle, is_archived=False)
        return success_response(
            request, code="DATA_RETRIEVED", message="Vehicle work expenses retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleWorkExpenseSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = VehicleWorkExpenseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant_id=vehicle.tenant_id, vehicle=vehicle, created_by=request.user)

        record_vehicle_timeline_event(
            vehicle=vehicle,
            category="work_expense",
            title=f"{instance.get_category_display()} added",
            description=f"₹{instance.amount:,.2f} — {instance.provider_name or instance.get_provider_type_display()}",
            metadata={"work_expense_id": str(instance.id), "amount": str(instance.amount)},
            actor=request.user,
        )
        return success_response(
            request, code="WORK_EXPENSE_CREATED", message="Vehicle work expense created successfully.",
            data=VehicleWorkExpenseSerializer(instance).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleWorkExpenseDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self, vehicle, pk):
        return get_object_or_404(VehicleWorkExpense, pk=pk, vehicle=vehicle, is_archived=False)

    def get(self, request, vehicle_id, pk):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        instance = self.get_object(vehicle, pk)
        return success_response(
            request, code="DATA_RETRIEVED", message="Vehicle work expense retrieved successfully.",
            data=VehicleWorkExpenseSerializer(instance).data, status_code=status.HTTP_200_OK,
        )

    def patch(self, request, vehicle_id, pk):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        instance = self.get_object(vehicle, pk)
        serializer = VehicleWorkExpenseSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        record_vehicle_timeline_event(
            vehicle=vehicle,
            category="work_expense",
            title=f"{serializer.instance.get_category_display()} updated",
            description=f"₹{serializer.instance.amount:,.2f}",
            actor=request.user,
        )
        return success_response(
            request, code="WORK_EXPENSE_UPDATED", message="Vehicle work expense updated successfully.",
            data=serializer.data, status_code=status.HTTP_200_OK,
        )

    def delete(self, request, vehicle_id, pk):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        instance = self.get_object(vehicle, pk)
        instance.archive()

        record_vehicle_timeline_event(
            vehicle=vehicle,
            category="work_expense",
            title=f"{instance.get_category_display()} removed",
            description=f"₹{instance.amount:,.2f}",
            actor=request.user,
        )
        return success_response(
            request, code="WORK_EXPENSE_ARCHIVED", message="Vehicle work expense archived successfully.",
            data={}, status_code=status.HTTP_200_OK,
        )


class VehiclePriceHistoryListAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehiclePriceHistory.objects.filter(vehicle=vehicle)
        return success_response(
            request, code="DATA_RETRIEVED", message="Price history retrieved successfully.",
            data=build_paginated_data(request, queryset, VehiclePriceHistorySerializer),
            status_code=status.HTTP_200_OK,
        )


class VehicleDocumentListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehicleDocument.objects.filter(vehicle=vehicle, is_archived=False)
        return success_response(
            request, code="DATA_RETRIEVED", message="Documents retrieved successfully.",
            data=VehicleDocumentSerializer(queryset, many=True).data, status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = VehicleDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant_id=vehicle.tenant_id, vehicle=vehicle, uploaded_by=request.user)

        record_vehicle_timeline_event(
            vehicle=vehicle,
            category="documents",
            title=f"{instance.get_document_type_display()} uploaded",
            actor=request.user,
        )
        return success_response(
            request, code="DOCUMENT_UPLOADED", message="Document uploaded successfully.",
            data=VehicleDocumentSerializer(instance).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleDocumentDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def delete(self, request, vehicle_id, pk):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        instance = get_object_or_404(VehicleDocument, pk=pk, vehicle=vehicle, is_archived=False)
        instance.archive()
        return success_response(
            request, code="DOCUMENT_ARCHIVED", message="Document archived successfully.",
            data={}, status_code=status.HTTP_200_OK,
        )


class VehicleTimelineListAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = vehicle.timeline_events.all()
        return success_response(
            request, code="DATA_RETRIEVED", message="Vehicle timeline retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleTimelineEventSerializer),
            status_code=status.HTTP_200_OK,
        )


class VehicleProfitabilityAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        return success_response(
            request, code="DATA_RETRIEVED", message="Profitability computed successfully.",
            data=compute_profitability(vehicle), status_code=status.HTTP_200_OK,
        )


def _require_tenant_id(request):
    """Returns (tenant_id, error_response) — exactly one is None. Shared by
    the tenant-wide (not single-vehicle-scoped) views below."""
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


class PortfolioProfitabilityInsightsAPIView(APIView):
    """Aggregate profitability across all confirmed sales, for the Inventory
    list page's Insights section — not scoped to a single vehicle."""

    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request):
        tenant_id, error = _require_tenant_id(request)
        if error:
            return error
        return success_response(
            request, code="DATA_RETRIEVED", message="Profitability insights computed successfully.",
            data=compute_portfolio_profitability_insights(tenant_id), status_code=status.HTTP_200_OK,
        )


def _parse_sales_report_filters(request):
    return (
        request.query_params.get("date_from", "").strip(),
        request.query_params.get("date_to", "").strip(),
        request.query_params.get("inventory_type", "").strip(),
        request.query_params.get("status", "").strip(),
    )


def _require_sales_report_date_range(request):
    """Returns (date_from, date_to, error_response) — exactly one of the last two is None."""
    date_from, date_to, _, _ = _parse_sales_report_filters(request)
    if not date_from or not date_to:
        return None, None, error_response(
            request,
            code="DATE_RANGE_REQUIRED",
            message="A date range is required to generate this report.",
            error="Both date_from and date_to query parameters are required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return date_from, date_to, None


class VehicleSalesReportListAPIView(APIView):
    """GET /api/v1/dealer-sales/reports/sales/ — paginated preview table for
    the Vehicle Sales Report. Same row source as the summary/export below."""

    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request):
        tenant_id, error = _require_tenant_id(request)
        if error:
            return error
        date_from, date_to, inventory_type, status_param = _parse_sales_report_filters(request)
        queryset = sales_report_queryset(
            tenant_id, date_from=date_from or None, date_to=date_to or None,
            inventory_type=inventory_type, status=status_param,
        )
        return success_response(
            request, code="DATA_RETRIEVED", message="Vehicle sales report retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleSalesReportRowSerializer),
            status_code=status.HTTP_200_OK,
        )


class VehicleSalesReportSummaryAPIView(APIView):
    """
    GET /api/v1/dealer-sales/reports/sales/summary/

    KPIs for the Vehicle Sales Report. Unlike the invoice report's summary
    (a pure DB-side Sum()), profit isn't a stored column here — owned-sale
    profit depends on acquisition + work-expense rows, consignment profit on
    a Settlement row — so this sums compute_sale_profit() per matching sale.
    Fine at dealer-inventory scale (tens to low hundreds of sales/range, not
    the thousands a service-invoice report might see). date_from/date_to
    required, matching the invoice report's convention.
    """

    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request):
        tenant_id, error = _require_tenant_id(request)
        if error:
            return error
        date_from, date_to, date_error = _require_sales_report_date_range(request)
        if date_error:
            return date_error
        _, _, inventory_type, status_param = _parse_sales_report_filters(request)

        sales = sales_report_queryset(
            tenant_id, date_from=date_from, date_to=date_to,
            inventory_type=inventory_type, status=status_param,
        )

        from decimal import Decimal
        count = 0
        cancelled_count = 0
        total_sale_value = Decimal("0.00")
        total_discount = Decimal("0.00")
        total_profit = Decimal("0.00")
        margin_sum = Decimal("0.00")
        margin_count = 0

        for sale in sales:
            count += 1
            if sale.status == VehicleSale.STATUS_CANCELLED:
                cancelled_count += 1
                continue
            total_sale_value += sale.final_sale_price
            total_discount += sale.discount_amount or Decimal("0.00")
            profit_data = compute_sale_profit(sale)
            if profit_data:
                total_profit += profit_data["profit"]
                if profit_data["margin_percent"] is not None:
                    margin_sum += profit_data["margin_percent"]
                    margin_count += 1

        return success_response(
            request, code="DATA_RETRIEVED", message="Vehicle sales report summary retrieved successfully.",
            data={
                "count": count,
                "cancelled_count": cancelled_count,
                "total_sale_value": str(total_sale_value),
                "total_discount": str(total_discount),
                "total_profit": str(total_profit),
                "average_margin_percent": str(margin_sum / margin_count) if margin_count else None,
            },
            status_code=status.HTTP_200_OK,
        )


class VehicleSalesReportExportAPIView(APIView):
    """GET /api/v1/dealer-sales/reports/sales/export/ — streams the Vehicle
    Sales Report as CSV straight from the DB cursor, same row source and
    column math as the summary/preview above. date_from/date_to required."""

    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request):
        tenant_id, error = _require_tenant_id(request)
        if error:
            return error
        date_from, date_to, date_error = _require_sales_report_date_range(request)
        if date_error:
            return date_error
        _, _, inventory_type, status_param = _parse_sales_report_filters(request)

        sales = sales_report_queryset(
            tenant_id, date_from=date_from, date_to=date_to,
            inventory_type=inventory_type, status=status_param,
        )

        from django.http import StreamingHttpResponse

        def row_stream():
            import csv
            import io

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "Sale Date", "Vehicle", "Reg. No", "Type", "Buyer", "Salesperson",
                "Sale Amount", "Discount", "Profit", "Margin %", "Status",
            ])
            yield buf.getvalue()

            for sale in sales.iterator(chunk_size=500):
                buf.seek(0)
                buf.truncate(0)
                vehicle = sale.vehicle
                profit_data = compute_sale_profit(sale) if sale.status == VehicleSale.STATUS_CONFIRMED else None
                salesperson_name = ""
                if sale.salesperson_id:
                    try:
                        salesperson_name = sale.salesperson.pii.get_full_name() or ""
                    except Exception:
                        salesperson_name = ""
                writer.writerow([
                    sale.sale_date.strftime("%Y-%m-%d"),
                    f"{vehicle.year} {vehicle.brand.name} {vehicle.vehicle_model.name}",
                    vehicle.registration_no or "",
                    "Consignment" if vehicle.inventory_type == InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT else "Owned",
                    sale.buyer.full_name,
                    salesperson_name,
                    sale.final_sale_price,
                    sale.discount_amount,
                    profit_data["profit"] if profit_data else "",
                    f"{profit_data['margin_percent']:.2f}" if profit_data and profit_data["margin_percent"] is not None else "",
                    "Cancelled" if sale.status == VehicleSale.STATUS_CANCELLED else "Confirmed",
                ])
                yield buf.getvalue()

        filename = f"vehicle_sales_report_{date_from}_to_{date_to}.csv"
        response = StreamingHttpResponse(row_stream(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Quotation → Negotiation → Reservation → Booking → Sale →
# Delivery → Settlement
# ─────────────────────────────────────────────────────────────────────────


class VehicleSaleQuotationListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehicleSaleQuotation.objects.filter(vehicle=vehicle, is_archived=False)
        return success_response(
            request, code="DATA_RETRIEVED", message="Quotations retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleSaleQuotationSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = QuotationCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quotation = create_quotation(vehicle=vehicle, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="QUOTATION_CREATED", message="Quotation created successfully.",
            data=VehicleSaleQuotationSerializer(quotation).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleSaleQuotationDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        return success_response(
            request, code="DATA_RETRIEVED", message="Quotation retrieved successfully.",
            data=VehicleSaleQuotationSerializer(quotation).data, status_code=status.HTTP_200_OK,
        )


class VehicleSaleQuotationSendAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        try:
            send_quotation(quotation, user=request.user)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="QUOTATION_SENT", message="Quotation sent successfully.",
            data=VehicleSaleQuotationSerializer(quotation).data, status_code=status.HTTP_200_OK,
        )


class VehicleNegotiationListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        return success_response(
            request, code="DATA_RETRIEVED", message="Negotiations retrieved successfully.",
            data=VehicleNegotiationSerializer(quotation.negotiations.all(), many=True).data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        serializer = NegotiationCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            negotiation = add_negotiation_round(quotation, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="NEGOTIATION_ADDED", message="Negotiation round added successfully.",
            data=VehicleNegotiationSerializer(negotiation).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleSaleQuotationAcceptAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        try:
            accept_quotation(quotation, user=request.user)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="QUOTATION_ACCEPTED", message="Quotation accepted successfully.",
            data=VehicleSaleQuotationSerializer(quotation).data, status_code=status.HTTP_200_OK,
        )


class VehicleSaleQuotationRejectAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reject_quotation(quotation, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="QUOTATION_REJECTED", message="Quotation rejected successfully.",
            data=VehicleSaleQuotationSerializer(quotation).data, status_code=status.HTTP_200_OK,
        )


class VehicleSaleQuotationCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        quotation, error = _resolve_tenant_object(
            request, VehicleSaleQuotation, pk,
            not_found_code="QUOTATION_NOT_FOUND", not_found_message="Quotation not found.",
        )
        if error:
            return error
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cancel_quotation(quotation, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="QUOTATION_CANCELLED", message="Quotation cancelled successfully.",
            data=VehicleSaleQuotationSerializer(quotation).data, status_code=status.HTTP_200_OK,
        )


class VehicleReservationListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehicleReservation.objects.filter(vehicle=vehicle, is_archived=False)
        return success_response(
            request, code="DATA_RETRIEVED", message="Reservations retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleReservationSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = ReservationCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reservation = create_reservation(vehicle=vehicle, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="RESERVATION_CREATED", message="Reservation created successfully.",
            data=VehicleReservationSerializer(reservation).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleReservationCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        reservation, error = _resolve_tenant_object(
            request, VehicleReservation, pk,
            not_found_code="RESERVATION_NOT_FOUND", not_found_message="Reservation not found.",
        )
        if error:
            return error
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancel_reservation(reservation, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="RESERVATION_CANCELLED", message="Reservation cancelled successfully.",
            data=VehicleReservationSerializer(reservation).data, status_code=status.HTTP_200_OK,
        )


class VehicleBookingListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehicleBooking.objects.filter(vehicle=vehicle, is_archived=False)
        return success_response(
            request, code="DATA_RETRIEVED", message="Bookings retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleBookingSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = BookingCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            booking = create_booking(vehicle=vehicle, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="BOOKING_CREATED", message="Booking created successfully.",
            data=VehicleBookingSerializer(booking).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleBookingCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        booking, error = _resolve_tenant_object(
            request, VehicleBooking, pk,
            not_found_code="BOOKING_NOT_FOUND", not_found_message="Booking not found.",
        )
        if error:
            return error
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancel_booking(booking, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="BOOKING_CANCELLED", message="Booking cancelled successfully.",
            data=VehicleBookingSerializer(booking).data, status_code=status.HTTP_200_OK,
        )


class VehicleSaleListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        queryset = VehicleSale.objects.filter(vehicle=vehicle, is_archived=False)
        return success_response(
            request, code="DATA_RETRIEVED", message="Sales retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleSaleSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, vehicle_id):
        vehicle, error = _resolve_vehicle(request, vehicle_id)
        if error:
            return error
        serializer = SaleCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sale = confirm_sale(vehicle=vehicle, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="SALE_CONFIRMED", message="Sale confirmed successfully.",
            data=VehicleSaleSerializer(sale).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleSaleCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk,
            not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        serializer = ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancel_sale(sale, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="SALE_CANCELLED", message="Sale cancelled successfully.",
            data=VehicleSaleSerializer(sale).data, status_code=status.HTTP_200_OK,
        )


class VehicleDeliveryDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        delivery = getattr(sale, "delivery", None)
        return success_response(
            request, code="DATA_RETRIEVED", message="Delivery retrieved successfully.",
            data=VehicleDeliverySerializer(delivery).data if delivery else None, status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        if getattr(sale, "delivery", None) is not None:
            return error_response(
                request, code="DELIVERY_ALREADY_EXISTS", message="This sale already has a delivery record.",
                error="This sale already has a delivery record.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        serializer = DeliveryCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = create_delivery(sale=sale, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="DELIVERY_CREATED", message="Delivery recorded successfully.",
            data=VehicleDeliverySerializer(delivery).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleSettlementDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        settlement = getattr(sale, "settlement", None)
        return success_response(
            request, code="DATA_RETRIEVED", message="Settlement retrieved successfully.",
            data=VehicleSettlementSerializer(settlement).data if settlement else None, status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        if getattr(sale, "settlement", None) is not None:
            return error_response(
                request, code="SETTLEMENT_ALREADY_EXISTS", message="This sale already has a settlement record.",
                error="This sale already has a settlement record.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        serializer = SettlementCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            settlement = create_settlement(sale, user=request.user, **serializer.validated_data)
        except DealerSalesError as exc:
            return _dealer_sales_error_response(request, exc)
        return success_response(
            request, code="SETTLEMENT_CREATED", message="Settlement created successfully.",
            data=VehicleSettlementSerializer(settlement).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleSettlementMarkPaidAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        settlement = getattr(sale, "settlement", None)
        if settlement is None:
            return error_response(
                request, code="SETTLEMENT_NOT_FOUND", message="This sale has no settlement record.",
                error="This sale has no settlement record.", status_code=status.HTTP_404_NOT_FOUND,
            )
        serializer = SettlementMarkPaidInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settlement = mark_settlement_paid(settlement, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="SETTLEMENT_PAID", message="Settlement marked as paid successfully.",
            data=VehicleSettlementSerializer(settlement).data, status_code=status.HTTP_200_OK,
        )


class VehicleSaleInvoiceDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        invoice = getattr(sale, "invoice", None)
        return success_response(
            request, code="DATA_RETRIEVED", message="Invoice retrieved successfully.",
            data=VehicleSaleInvoiceSerializer(invoice).data if invoice else None, status_code=status.HTTP_200_OK,
        )

    def post(self, request, pk):
        sale, error = _resolve_tenant_object(
            request, VehicleSale, pk, not_found_code="SALE_NOT_FOUND", not_found_message="Sale not found.",
        )
        if error:
            return error
        if getattr(sale, "invoice", None) is not None:
            return error_response(
                request, code="INVOICE_ALREADY_EXISTS", message="This sale already has an invoice.",
                error="This sale already has an invoice.", status_code=status.HTTP_400_BAD_REQUEST,
            )
        serializer = InvoiceCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = generate_sale_invoice(sale, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="INVOICE_GENERATED", message="Invoice generated successfully.",
            data=VehicleSaleInvoiceSerializer(invoice).data, status_code=status.HTTP_201_CREATED,
        )


class VehicleSaleInvoiceRecordPaymentAPIView(APIView):
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        invoice, error = _resolve_tenant_object(
            request, VehicleSaleInvoice, pk,
            not_found_code="INVOICE_NOT_FOUND", not_found_message="Invoice not found.",
        )
        if error:
            return error
        serializer = InvoicePaymentCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record_sale_invoice_payment(invoice, user=request.user, **serializer.validated_data)
        return success_response(
            request, code="PAYMENT_RECORDED", message="Payment recorded successfully.",
            data=VehicleSaleInvoiceSerializer(invoice).data, status_code=status.HTTP_200_OK,
        )


class VehicleSaleInvoicePreviewHtmlAPIView(APIView):
    """
    GET /api/v1/dealer-sales/invoices/:pk/preview-html/

    Returns the raw HTML used to generate the invoice PDF, for an in-app
    iframe preview — same template/context as the PDF, so preview and
    download are guaranteed to match (mirrors
    apps.platform.invoices.views.InvoicePreviewHtmlAPIView).
    """
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def get(self, request, pk):
        invoice, error = _resolve_tenant_object(
            request, VehicleSaleInvoice, pk,
            not_found_code="INVOICE_NOT_FOUND", not_found_message="Invoice not found.",
        )
        if error:
            return error

        from django.http import HttpResponse

        from apps.platform.dealer_sales.pdf_service import render_preview_html
        return HttpResponse(render_preview_html(invoice), content_type="text/html")


class VehicleSaleInvoicePdfAPIView(APIView):
    """
    POST /api/v1/dealer-sales/invoices/:pk/generate-pdf/?force=true

    Generates (or returns the cached) PDF for a dealer sale invoice and
    returns its URL — mirrors apps.platform.invoices.views.InvoicePdfAPIView,
    minus the GST-invoice-specific layout toggles that don't apply here.
    """
    permission_classes = [IsAuthenticatedDealerSalesAccess]

    def post(self, request, pk):
        invoice, error = _resolve_tenant_object(
            request, VehicleSaleInvoice, pk,
            not_found_code="INVOICE_NOT_FOUND", not_found_message="Invoice not found.",
        )
        if error:
            return error

        from apps.platform.dealer_sales.pdf_service import (
            PdfGenerationError,
            PdfNotAvailableError,
            SaleInvoicePdfService,
        )

        force = request.query_params.get("force", "false").strip().lower() in {"true", "1", "yes"}
        already_had_pdf = bool(invoice.pdf_key) and not force

        try:
            pdf_key = SaleInvoicePdfService.generate_and_store(invoice, force=force)
        except PdfNotAvailableError as exc:
            return error_response(
                request, code="PDF_DEPENDENCY_MISSING", message=str(exc),
                error="weasyprint must be installed to generate PDFs.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PdfGenerationError as exc:
            return error_response(
                request, code="PDF_GENERATION_FAILED", message=str(exc),
                error="An error occurred while generating the invoice PDF.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_url = SaleInvoicePdfService.resolve_url(pdf_key)
        return success_response(
            request, code="PDF_READY", message="Invoice PDF is ready.",
            data={"pdf_url": pdf_url, "generated": not already_had_pdf},
            status_code=status.HTTP_200_OK if already_had_pdf else status.HTTP_201_CREATED,
        )
