from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.platform.leads.models import Lead
from apps.platform.leads.serializers import PublicLeadEnquirySerializer
from apps.platform.leads.services import create_lead
from apps.platform.portfolio.models import InventoryVehicle
from apps.platform.tenants.models import Tenant
from core.utils.api_response import error_response, success_response

# Duplicate/double-submit guard: the same (tenant, phone, vehicle) combo
# within this window doesn't create a second Lead row — a cheap spam/retry
# guard that needs no extra infrastructure (see leads module plan, §8).
DUPLICATE_WINDOW_MINUTES = 30


def _resolve_public_tenant(request, domain: str):
    """Mirrors apps.platform.portfolio.public_views._resolve_public_tenant."""
    domain = domain.strip().lower()
    if not domain:
        return None, error_response(
            request,
            code="INVALID_DOMAIN",
            message="Domain parameter is required.",
            error="Missing domain.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    tenant = Tenant.objects.filter(domain__istartswith=f"{domain}.", status="active", is_archived=False).first()
    if tenant is None:
        return None, error_response(
            request,
            code="TENANT_NOT_FOUND",
            message="No active tenant found for the given domain.",
            error="Tenant not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return tenant, None


def _fake_success(request):
    # Honeypot tripped: respond exactly like a real success so a bot can't
    # distinguish "rejected" from "accepted" and adjust its behavior.
    return success_response(
        request,
        code="LEAD_CREATED",
        message="Thanks — we'll be in touch shortly.",
        data={},
        status_code=status.HTTP_201_CREATED,
    )


def _is_duplicate(tenant, phone, vehicle):
    cutoff = timezone.now() - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
    return Lead.objects.filter(
        tenant=tenant, phone=phone, vehicle=vehicle, created_at__gte=cutoff
    ).exists()


class PublicLeadCreateAPIView(APIView):
    """Anonymous general enquiry — no portal login required (unlike
    VisitRequest), matching how real used-car marketplaces let a visitor
    submit "Enquire Now" without an account."""

    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_lead_enquiry"

    def post(self, request, domain: str):
        tenant, error = _resolve_public_tenant(request, domain)
        if error:
            return error

        serializer = PublicLeadEnquirySerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("website"):
            return _fake_success(request)

        if _is_duplicate(tenant, data["phone"], None):
            return _fake_success(request)

        create_lead(
            tenant_id=tenant.id,
            created_by=None,
            changed_by=None,
            is_self_logged=False,
            source=Lead.SOURCE_PUBLIC_ENQUIRY,
            enquiry_type=data.get("enquiry_type") or Lead.ENQUIRY_GENERAL_SEARCH,
            full_name=data["full_name"],
            phone=data["phone"],
            email=data.get("email"),
            preferred_brand=data.get("preferred_brand"),
            preferred_vehicle_type=data.get("preferred_vehicle_type"),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            message=data.get("message"),
        )
        return success_response(
            request,
            code="LEAD_CREATED",
            message="Thanks — we'll be in touch shortly.",
            data={},
            status_code=status.HTTP_201_CREATED,
        )


class PublicVehicleEnquiryCreateAPIView(APIView):
    """Anonymous "Enquire about this car" — same no-auth rule as
    PublicLeadCreateAPIView, scoped to one specific, publicly-visible
    InventoryVehicle (same visibility rule as PublicInventoryVehicleDetailAPIView)."""

    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_lead_enquiry"

    def post(self, request, domain: str, pk):
        tenant, error = _resolve_public_tenant(request, domain)
        if error:
            return error

        vehicle = InventoryVehicle.objects.filter(
            tenant=tenant, pk=pk, status__in=[InventoryVehicle.STATUS_AVAILABLE, InventoryVehicle.STATUS_BOOKED],
            is_archived=False,
        ).first()
        if vehicle is None:
            return error_response(
                request,
                code="VEHICLE_NOT_FOUND",
                message="Vehicle not found.",
                error="No matching vehicle for this tenant.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = PublicLeadEnquirySerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("website"):
            return _fake_success(request)

        if _is_duplicate(tenant, data["phone"], vehicle):
            return _fake_success(request)

        create_lead(
            tenant_id=tenant.id,
            created_by=None,
            changed_by=None,
            is_self_logged=False,
            source=Lead.SOURCE_PUBLIC_ENQUIRY,
            enquiry_type=Lead.ENQUIRY_SPECIFIC_VEHICLE,
            vehicle=vehicle,
            full_name=data["full_name"],
            phone=data["phone"],
            email=data.get("email"),
            message=data.get("message"),
        )
        return success_response(
            request,
            code="LEAD_CREATED",
            message="Thanks — we'll be in touch shortly.",
            data={},
            status_code=status.HTTP_201_CREATED,
        )
