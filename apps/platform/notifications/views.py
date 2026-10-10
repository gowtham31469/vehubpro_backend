from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.platform.notifications.models import Notification
from apps.platform.notifications.serializers import NotificationSerializer
from core.utils.api_response import success_response
from core.utils.pagination import build_paginated_data


class NotificationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Notification.objects.filter(user=request.user)
        if request.query_params.get("unread") == "true":
            queryset = queryset.filter(is_read=False)

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Notifications retrieved successfully.",
            data=build_paginated_data(request, queryset, NotificationSerializer),
            status_code=status.HTTP_200_OK,
        )


class NotificationUnreadCountAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Unread notification count retrieved successfully.",
            data={"count": count},
            status_code=status.HTTP_200_OK,
        )


class NotificationMarkReadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, user=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at", "updated_at"])
        return success_response(
            request,
            code="NOTIFICATION_READ",
            message="Notification marked as read.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class NotificationMarkAllReadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        now = timezone.now()
        Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True, read_at=now, updated_at=now
        )
        return success_response(
            request,
            code="NOTIFICATIONS_READ",
            message="All notifications marked as read.",
            data={},
            status_code=status.HTTP_200_OK,
        )
