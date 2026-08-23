from rest_framework import serializers

from apps.platform.masters.models import City, Role, State


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name", "description"]


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ["id", "name", "code", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class CitySerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source="state.name", read_only=True)

    class Meta:
        model = City
        fields = ["id", "state", "state_name", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at", "state_name"]
