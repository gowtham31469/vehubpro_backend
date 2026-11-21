from datetime import date

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.customers.models import Customer
from apps.platform.leads.models import Lead
from apps.platform.leads.permissions import IsAuthenticatedLeadsAccess
from apps.platform.leads.serializers import (
    LeadConvertToInventorySerializer,
    LeadCreateSerializer,
    LeadSerializer,
    LeadStatusEventSerializer,
)
from apps.platform.leads.services import (
    LostReasonRequired,
    convert_lead_to_customer,
    convert_lead_to_inventory,
    create_lead,
    transition_lead_status,
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


class LeadListAPIView(APIView):
    permission_classes = [IsAuthenticatedLeadsAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        queryset = Lead.objects.select_related(
            "vehicle", "vehicle__brand", "vehicle__vehicle_model", "customer", "assigned_to",
            "preferred_brand", "preferred_vehicle_type",
        ).filter(tenant_id=tenant_id, is_archived=False)

        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        assigned_to = request.query_params.get("assigned_to")
        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)

        due = request.query_params.get("due")
        today = date.today()
        if due == "today":
            queryset = queryset.filter(next_follow_up_at=today)
        elif due == "overdue":
            queryset = queryset.filter(next_follow_up_at__lt=today)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
                | Q(vehicle__brand__name__icontains=search)
                | Q(vehicle__vehicle_model__name__icontains=search)
            )

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Leads retrieved successfully.",
            data=build_paginated_data(request, queryset, LeadSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        serializer = LeadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lead = create_lead(
            tenant_id=tenant_id,
            created_by=request.user,
            changed_by=request.user,
            is_self_logged=True,
            source=serializer.validated_data.get("source") or Lead.SOURCE_WALK_IN,
            **{k: v for k, v in serializer.validated_data.items() if k != "source"},
        )
        return success_response(
            request,
            code="LEAD_CREATED",
            message="Lead created successfully.",
            data=LeadSerializer(lead).data,
            status_code=status.HTTP_201_CREATED,
        )


class LeadDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedLeadsAccess]

    def get_object(self, tenant_id, pk):
        return get_object_or_404(Lead, pk=pk, tenant_id=tenant_id, is_archived=False)

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(tenant_id, pk)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Lead retrieved successfully.",
            data=LeadSerializer(instance).data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        instance = self.get_object(tenant_id, pk)
        payload = request.data

        if "status" in payload and payload["status"] != instance.status:
            try:
                transition_lead_status(
                    instance,
                    payload["status"],
                    note=payload.get("staff_notes"),
                    changed_by=request.user,
                    lost_reason=payload.get("lost_reason"),
                    lost_notes=payload.get("lost_notes"),
                )
            except LostReasonRequired as exc:
                return error_response(
                    request,
                    code="LOST_REASON_REQUIRED",
                    message=str(exc),
                    error=str(exc),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        serializer = LeadSerializer(instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return success_response(
            request,
            code="LEAD_UPDATED",
            message="Lead updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class LeadEventListAPIView(APIView):
    permission_classes = [IsAuthenticatedLeadsAccess]

    def get(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        lead = get_object_or_404(Lead, pk=pk, tenant_id=tenant_id, is_archived=False)
        events = lead.status_events.select_related("changed_by__pii").all()
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Lead history retrieved successfully.",
            data=LeadStatusEventSerializer(events, many=True).data,
            status_code=status.HTTP_200_OK,
        )


class LeadConvertAPIView(APIView):
    permission_classes = [IsAuthenticatedLeadsAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        lead = get_object_or_404(Lead, pk=pk, tenant_id=tenant_id, is_archived=False)

        customer = None
        customer_id = request.data.get("customer_id")
        new_customer_fields = request.data.get("new_customer")

        if customer_id:
            customer = get_object_or_404(Customer, pk=customer_id, tenant_id=tenant_id, is_archived=False)
        elif not new_customer_fields:
            return error_response(
                request,
                code="CUSTOMER_REQUIRED",
                message="Provide either customer_id or new_customer.",
                error="customer_id or new_customer is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        customer = convert_lead_to_customer(
            lead, customer=customer, new_customer_fields=new_customer_fields, created_by=request.user
        )
        return success_response(
            request,
            code="LEAD_CONVERTED",
            message="Lead converted to customer successfully.",
            data={"customer_id": str(customer.id), "lead": LeadSerializer(lead).data},
            status_code=status.HTTP_200_OK,
        )


class LeadConvertToInventoryAPIView(APIView):
    """Trade-in leads only — appraises the customer's vehicle into a new
    InventoryVehicle + VehicleAcquisition(acquisition_method='trade_in')."""

    permission_classes = [IsAuthenticatedLeadsAccess]

    def post(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error

        lead = get_object_or_404(Lead, pk=pk, tenant_id=tenant_id, is_archived=False)

        serializer = LeadConvertToInventorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        vehicle = convert_lead_to_inventory(
            lead,
            vehicle_type=data["vehicle_type"],
            brand=data["brand"],
            vehicle_model=data["vehicle_model"],
            fuel_type=data["fuel_type"],
            year=data["year"],
            mileage_km=data.get("mileage_km", 0),
            registration_no=data.get("registration_no", ""),
            listing_price=data.get("listing_price", 0),
            purchase_price=data.get("purchase_price"),
            acquisition_date=data.get("acquisition_date"),
            created_by=request.user,
        )
        return success_response(
            request,
            code="LEAD_CONVERTED",
            message="Lead converted to an inventory vehicle successfully.",
            data={"vehicle_id": str(vehicle.id), "lead": LeadSerializer(lead).data},
            status_code=status.HTTP_200_OK,
        )
