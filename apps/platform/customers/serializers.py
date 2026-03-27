from rest_framework import serializers
from uuid import UUID

from apps.platform.customers.models import Customer
from apps.platform.masters.models import City, State


class CustomerSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source="state.name", read_only=True)
    city_name = serializers.CharField(source="city.name", read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "tenant",
            "customer_code",
            "full_name",
            "email",
            "phone",
            "alternate_phone",
            "address",
            "city",
            "state",
            "city_name",
            "state_name",
            "postal_code",
            "status",
            "notes",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "archived_at", "created_at", "updated_at", "city_name", "state_name"]

    @staticmethod
    def _is_uuid(value) -> bool:
        try:
            UUID(str(value))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def to_internal_value(self, data):
        mutable = data.copy()

        state_value = mutable.get("state")
        state_obj = None
        if isinstance(state_value, str):
            state_name = state_value.strip()
            if state_name and not self._is_uuid(state_name):
                state_obj, _ = State.objects.get_or_create(name=state_name, defaults={"is_active": True})
                mutable["state"] = str(state_obj.id)

        city_value = mutable.get("city")
        if isinstance(city_value, str):
            city_name = city_value.strip()
            if city_name and not self._is_uuid(city_name):
                if not state_obj:
                    state_id = mutable.get("state")
                    if state_id:
                        try:
                            state_obj = State.objects.get(pk=state_id)
                        except State.DoesNotExist:
                            state_obj = None
                if not state_obj:
                    raise serializers.ValidationError({"state": "State is required when city is provided as text."})
                city_obj, _ = City.objects.get_or_create(
                    state=state_obj,
                    name=city_name,
                    defaults={"is_active": True},
                )
                mutable["city"] = str(city_obj.id)

        return super().to_internal_value(mutable)

    def validate_email(self, value):
        return value.lower().strip() if value else value

    def validate_phone(self, value):
        phone = (value or "").strip()
        if not phone:
            raise serializers.ValidationError("Phone number is required.")
        return phone

    def validate_full_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Customer name is required.")
        return name

    def validate(self, attrs):
        state = attrs.get("state", getattr(self.instance, "state", None))
        city = attrs.get("city", getattr(self.instance, "city", None))
        if city and state and city.state_id != state.id:
            raise serializers.ValidationError(
                {"city": "Selected city does not belong to the selected state."}
            )
        return attrs
