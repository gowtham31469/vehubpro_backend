from datetime import timedelta

from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.platform.portfolio.models import InventoryVehicle, VisitRequest
from apps.platform.portfolio.serializers import PublicInventoryVehicleSerializer
from apps.platform.tenants.models import Tenant
from apps.platform.users.models import User
from core.audit.constants import AuditAction, AuditModule
from core.audit.service import log_audit_event
from core.auth.views import _build_auth_claims
from core.utils.api_response import error_response, success_response

from apps.portal.models import WishlistItem
from apps.portal.permissions import IsCustomerRole
from apps.portal.serializers import (
    ChangePasswordSerializer,
    CustomerLoginSerializer,
    CustomerSignupSerializer,
    ProfileSerializer,
    VisitRequestCreateSerializer,
)

# Customers stay logged in much longer than staff on a shared device concern
# is lower for the public storefront — 30 days instead of the global
# SIMPLE_JWT default used for staff logins (core/auth/views.py). Applied both
# at issuance (login/signup, below) and on every rotation
# (CustomerTokenRefreshAPIView), since simplejwt's generic refresh endpoint
# would otherwise reset it back to the global default on each rotation.
CUSTOMER_REFRESH_TOKEN_LIFETIME = timedelta(days=30)


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

    tenant = Tenant.objects.filter(
        domain__istartswith=f"{domain}.",
        status="active",
        is_archived=False,
    ).first()

    if tenant is None:
        return None, error_response(
            request,
            code="TENANT_NOT_FOUND",
            message="No active tenant found for the given domain.",
            error="Tenant not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return tenant, None


def _issue_tokens_response(request, user, email, code, message, audit_action):
    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=CUSTOMER_REFRESH_TOKEN_LIFETIME)
    claims = _build_auth_claims(user)
    for key, value in claims.items():
        refresh[key] = value

    full_name = ""
    try:
        full_name = user.pii.get_full_name() or ""
    except Exception:
        pass

    response_data = {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": {
            "id": str(user.id),
            "email": email,
            "full_name": full_name,
            **claims,
        },
    }

    log_audit_event(
        actor_id=str(user.id),
        actor_type="customer",
        action=audit_action,
        module=AuditModule.AUTH,
        ip_address=request.META.get("REMOTE_ADDR"),
        method=request.method,
        endpoint=request.path,
        headers={"user_agent": request.headers.get("User-Agent")},
    )

    return success_response(
        request,
        code=code,
        message=message,
        data=response_data,
        status_code=status.HTTP_200_OK,
    )


class CustomerSignupAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, domain: str):
        tenant, error = _resolve_public_tenant(request, domain)
        if error:
            return error

        serializer = CustomerSignupSerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return _issue_tokens_response(
            request,
            user,
            serializer.validated_data["email"],
            code="SIGNUP_SUCCESS",
            message="Account created successfully.",
            audit_action=AuditAction.CREATE,
        )


class CustomerLoginAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, domain: str):
        tenant, error = _resolve_public_tenant(request, domain)
        if error:
            return error

        serializer = CustomerLoginSerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        email = serializer.validated_data["email"]

        return _issue_tokens_response(
            request,
            user,
            email,
            code="LOGIN_SUCCESS",
            message="Login successful.",
            audit_action=AuditAction.LOGIN,
        )


class ProfileAPIView(APIView):
    permission_classes = [IsCustomerRole]

    def get(self, request):
        serializer = ProfileSerializer(request.user)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Profile retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="PROFILE_UPDATED",
            message="Profile updated successfully.",
            data=ProfileSerializer(request.user).data,
            status_code=status.HTTP_200_OK,
        )


class ChangePasswordAPIView(APIView):
    permission_classes = [IsCustomerRole]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        log_audit_event(
            actor_id=str(request.user.id),
            actor_type="customer",
            action=AuditAction.UPDATE,
            module=AuditModule.AUTH,
            ip_address=request.META.get("REMOTE_ADDR"),
            method=request.method,
            endpoint=request.path,
            headers={"user_agent": request.headers.get("User-Agent")},
        )

        return success_response(
            request,
            code="PASSWORD_CHANGED",
            message="Password changed successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class WishlistListAPIView(APIView):
    permission_classes = [IsCustomerRole]

    def get(self, request):
        vehicles = InventoryVehicle.objects.filter(
            wishlisted_by__user=request.user, tenant_id=request.user.tenant_id
        ).order_by("-wishlisted_by__created_at")
        serializer = PublicInventoryVehicleSerializer(vehicles, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Wishlist retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class WishlistItemAPIView(APIView):
    permission_classes = [IsCustomerRole]

    def _get_vehicle(self, request, vehicle_id):
        return InventoryVehicle.objects.filter(
            id=vehicle_id, tenant_id=request.user.tenant_id, is_archived=False
        ).first()

    def post(self, request, vehicle_id):
        vehicle = self._get_vehicle(request, vehicle_id)
        if vehicle is None:
            return error_response(
                request,
                code="VEHICLE_NOT_FOUND",
                message="Vehicle not found.",
                error="Vehicle not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        WishlistItem.objects.get_or_create(user=request.user, vehicle=vehicle)
        return success_response(
            request,
            code="WISHLIST_ADDED",
            message="Vehicle added to wishlist.",
            data={},
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, vehicle_id):
        WishlistItem.objects.filter(user=request.user, vehicle_id=vehicle_id).delete()
        return success_response(
            request,
            code="WISHLIST_REMOVED",
            message="Vehicle removed from wishlist.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class VisitRequestCreateAPIView(APIView):
    permission_classes = [IsCustomerRole]

    def post(self, request, vehicle_id):
        vehicle = InventoryVehicle.objects.filter(
            id=vehicle_id, tenant_id=request.user.tenant_id, is_archived=False
        ).first()
        if vehicle is None:
            return error_response(
                request,
                code="VEHICLE_NOT_FOUND",
                message="Vehicle not found.",
                error="Vehicle not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = VisitRequestCreateSerializer(
            data=request.data, context={"user": request.user, "vehicle": vehicle}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="VISIT_REQUESTED",
            message="Visit requested successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class MyVisitRequestsAPIView(APIView):
    permission_classes = [IsCustomerRole]

    def get(self, request):
        rows = VisitRequest.objects.filter(customer_user=request.user).values("vehicle_id", "status")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Visit requests retrieved successfully.",
            data=[{"vehicle": str(r["vehicle_id"]), "status": r["status"]} for r in rows],
            status_code=status.HTTP_200_OK,
        )


class CustomerTokenRefreshAPIView(APIView):
    """
    Customer-specific refresh/rotation — mirrors core.auth.views.RefreshTokenView
    but, unlike simplejwt's generic rotation (which always re-applies the
    global SIMPLE_JWT.REFRESH_TOKEN_LIFETIME), re-issues the rotated refresh
    token with CUSTOMER_REFRESH_TOKEN_LIFETIME every time, so a customer's
    30-day session actually persists across repeated refreshes instead of
    collapsing back to the staff default on the very next rotation.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        refresh_str = request.data.get("refresh")
        if not refresh_str:
            return error_response(
                request,
                code="REFRESH_REQUIRED",
                message="Refresh token is required.",
                error="Missing refresh token.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            old_refresh = RefreshToken(refresh_str)
        except TokenError:
            return error_response(
                request,
                code="INVALID_REFRESH_TOKEN",
                message="Invalid or expired refresh token.",
                error="Token is invalid or expired.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        user = (
            User.objects.filter(id=old_refresh.get("user_id"), is_active=True, is_archived=False)
            .select_related("role")
            .first()
        )
        if not user or not user.role or user.role.code != "CUSTOMER":
            return error_response(
                request,
                code="INVALID_REFRESH_TOKEN",
                message="Invalid refresh token.",
                error="Token does not belong to an active customer account.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            old_refresh.blacklist()
        except TokenError:
            pass

        new_refresh = RefreshToken.for_user(user)
        new_refresh.set_exp(lifetime=CUSTOMER_REFRESH_TOKEN_LIFETIME)
        for key, value in _build_auth_claims(user).items():
            new_refresh[key] = value

        return success_response(
            request,
            code="TOKEN_REFRESHED",
            message="Token refreshed successfully.",
            data={"access": str(new_refresh.access_token), "refresh": str(new_refresh)},
            status_code=status.HTTP_200_OK,
        )
