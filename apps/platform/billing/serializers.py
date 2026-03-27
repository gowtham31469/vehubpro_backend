from rest_framework import serializers

from apps.platform.billing.models import (
    Plan,
    SubscriptionAddOn,
    SubscriptionHistory,
    SubscriptionLedger,
    TenantSubscription,
)


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id",
            "code",
            "name",
            "description",
            "price",
            "billing_cycle",
            "is_custom",
            "is_active",
            "max_users",
            "max_vehicles",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]
        # Model unique=True adds UniqueValidator which runs before validate_code and
        # treats archived rows as conflicts with a generic message. Uniqueness is
        # enforced in validate_code (archived vs active messaging + DB constraint).
        extra_kwargs = {"code": {"validators": []}}

    def validate_code(self, value):
        if not value:
            return value
        code = value.strip()
        qs = Plan.objects.filter(code=code)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        existing = qs.first()
        if not existing:
            return code
        if existing.is_archived:
            raise serializers.ValidationError(
                "A plan with this code already exists but is archived. "
                "Unarchive that plan (set is_archived=false) or choose a different code."
            )
        raise serializers.ValidationError("A plan with this code already exists.")


class SubscriptionLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionLedger
        fields = [
            "id",
            "tenant",
            "event_type",
            "payload",
            "effective_at",
            "created_by",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class SubscriptionHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionHistory
        fields = [
            "id",
            "tenant",
            "plan",
            "start_date",
            "end_date",
            "billing_cycle",
            "price",
            "max_users",
            "max_vehicles",
            "change_reason",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class TenantSubscriptionSerializer(serializers.ModelSerializer):
    ledger_entry_details = SubscriptionLedgerSerializer(source="ledger_entry", read_only=True)
    plan_details = PlanSerializer(source="plan", read_only=True)

    class Meta:
        model = TenantSubscription
        fields = [
            "id",
            "tenant",
            "plan",
            "plan_details",
            "start_date",
            "end_date",
            "billing_cycle",
            "price",
            "max_users",
            "max_vehicles",
            "status",
            "ledger_entry",
            "ledger_entry_details",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class SubscriptionAddOnSerializer(serializers.ModelSerializer):
    subscription_details = TenantSubscriptionSerializer(source="subscription", read_only=True)
    ledger_entry_details = SubscriptionLedgerSerializer(source="ledger_entry", read_only=True)

    class Meta:
        model = SubscriptionAddOn
        fields = [
            "id",
            "subscription",
            "subscription_details",
            "ledger_entry",
            "ledger_entry_details",
            "type",
            "users_quantity",
            "vehicles_quantity",
            "unit_price",
            "start_date",
            "end_date",
            "is_active",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]
