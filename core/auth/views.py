from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from core.audit.constants import AuditAction, AuditModule
from core.audit.service import log_audit_event
from core.auth.serializers import LoginSerializer, LogoutSerializer
from core.utils.api_response import error_response, success_response


def _build_auth_claims(user):
    role = getattr(user, "role", None)
    tenant = getattr(user, "tenant", None)
    return {
        "role_id": str(role.id) if role else None,
        "role_name": role.name if role else None,
        "tenant_id": str(tenant.id) if tenant else None,
        "is_superuser": bool(user.is_superuser),
    }


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        email = serializer.validated_data["email"]

        refresh = RefreshToken.for_user(user)
        claims = _build_auth_claims(user)
        for key, value in claims.items():
            refresh[key] = value

        response_data = {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": str(user.id),
                "email": email,
                **claims,
            },
        }

        log_audit_event(
            actor_id=str(user.id),
            actor_type="user",
            action=AuditAction.LOGIN,
            module=AuditModule.AUTH,
            ip_address=request.META.get("REMOTE_ADDR"),
            method=request.method,
            endpoint=request.path,
            headers={"user_agent": request.headers.get("User-Agent")},
        )

        return success_response(
            request,
            code="LOGIN_SUCCESS",
            message="Login successful.",
            data=response_data,
            status_code=status.HTTP_200_OK,
        )


class RefreshTokenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(
            request,
            code="TOKEN_REFRESHED",
            message="Token refreshed successfully.",
            data=serializer.validated_data,
            status_code=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            token.blacklist()
        except TokenError:
            return error_response(
                request,
                code="INVALID_REFRESH_TOKEN",
                message="Invalid or expired refresh token.",
                data={},
                error="Token is invalid or expired.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = getattr(request, "user", None)
        actor_id = str(user.id) if getattr(user, "is_authenticated", False) else None
        log_audit_event(
            actor_id=actor_id,
            actor_type="user" if actor_id else "system_or_anonymous",
            action=AuditAction.LOGOUT,
            module=AuditModule.AUTH,
            ip_address=request.META.get("REMOTE_ADDR"),
            method=request.method,
            endpoint=request.path,
            headers={"user_agent": request.headers.get("User-Agent")},
        )

        return success_response(
            request,
            code="LOGOUT_SUCCESS",
            message="Logout successful.",
            data={},
            status_code=status.HTTP_200_OK,
        )
