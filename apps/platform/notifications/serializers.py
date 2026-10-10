from rest_framework import serializers

from apps.platform.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "message", "link", "is_read", "read_at", "created_at"]
        read_only_fields = fields
