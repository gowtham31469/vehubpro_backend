from rest_framework import serializers

from apps.platform.leads.models import Lead, LeadStatusEvent
from apps.platform.vehicles.models import BodyType, FuelType, VehicleBrand, VehicleModel


class LeadSerializer(serializers.ModelSerializer):
    """Staff-facing read + limited update (status/assignment/follow-up/notes).
    Contact/enquiry fields are set at creation and stay read-only afterwards —
    same convention as VisitRequestSerializer."""

    vehicle_brand_name = serializers.CharField(source="vehicle.brand.name", read_only=True, default=None)
    vehicle_model_name = serializers.CharField(source="vehicle.vehicle_model.name", read_only=True, default=None)
    vehicle_year = serializers.IntegerField(source="vehicle.year", read_only=True, default=None)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True, default=None)
    preferred_brand_name = serializers.CharField(source="preferred_brand.name", read_only=True, default=None)
    preferred_vehicle_type_name = serializers.CharField(
        source="preferred_vehicle_type.name", read_only=True, default=None
    )
    converted_vehicle_label = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id",
            "vehicle",
            "vehicle_brand_name",
            "vehicle_model_name",
            "vehicle_year",
            "customer",
            "customer_name",
            "full_name",
            "phone",
            "email",
            "enquiry_type",
            "preferred_brand",
            "preferred_brand_name",
            "preferred_vehicle_type",
            "preferred_vehicle_type_name",
            "budget_min",
            "budget_max",
            "trade_in_brand",
            "trade_in_model",
            "trade_in_year",
            "trade_in_registration_no",
            "trade_in_odometer_km",
            "trade_in_expected_price",
            "converted_vehicle",
            "converted_vehicle_label",
            "message",
            "source",
            "is_self_logged",
            "status",
            "assigned_to",
            "assigned_to_name",
            "next_follow_up_at",
            "last_contacted_at",
            "staff_notes",
            "lost_reason",
            "lost_notes",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "vehicle",
            "vehicle_brand_name",
            "vehicle_model_name",
            "vehicle_year",
            "customer",
            "customer_name",
            "full_name",
            "phone",
            "email",
            "enquiry_type",
            "preferred_brand",
            "preferred_brand_name",
            "preferred_vehicle_type",
            "preferred_vehicle_type_name",
            "budget_min",
            "budget_max",
            "trade_in_brand",
            "trade_in_model",
            "trade_in_year",
            "trade_in_registration_no",
            "trade_in_odometer_km",
            "trade_in_expected_price",
            "converted_vehicle",
            "converted_vehicle_label",
            "message",
            "source",
            "is_self_logged",
            "status",
            "lost_reason",
            "lost_notes",
            "created_at",
        ]

    def get_converted_vehicle_label(self, obj):
        if obj.converted_vehicle_id is None:
            return None
        v = obj.converted_vehicle
        return f"{v.year} {v.brand.name} {v.vehicle_model.name}"

    def get_assigned_to_name(self, obj):
        if obj.assigned_to_id is None:
            return None
        try:
            return obj.assigned_to.pii.get_full_name() or "Staff"
        except Exception:
            return "Staff"


class LeadCreateSerializer(serializers.ModelSerializer):
    """Staff "Add Lead" — walk-ins/phone calls (requirement 1c)."""

    class Meta:
        model = Lead
        fields = [
            "vehicle",
            "full_name",
            "phone",
            "email",
            "enquiry_type",
            "preferred_brand",
            "preferred_vehicle_type",
            "budget_min",
            "budget_max",
            "trade_in_brand",
            "trade_in_model",
            "trade_in_year",
            "trade_in_registration_no",
            "trade_in_odometer_km",
            "trade_in_expected_price",
            "message",
            "source",
            "assigned_to",
            "next_follow_up_at",
        ]

    def validate_full_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Name is required.")
        return name

    def validate_phone(self, value):
        phone = (value or "").strip()
        if not phone:
            raise serializers.ValidationError("Phone is required.")
        return phone

    def validate(self, attrs):
        enquiry_type = attrs.get("enquiry_type", Lead.ENQUIRY_SPECIFIC_VEHICLE)
        if enquiry_type == Lead.ENQUIRY_SPECIFIC_VEHICLE and not attrs.get("vehicle"):
            raise serializers.ValidationError({"vehicle": "Select a vehicle for a specific-vehicle enquiry."})
        return attrs


class LeadConvertToInventorySerializer(serializers.Serializer):
    """Trade-in leads only — staff confirms/picks the real catalog entries
    (the lead's trade_in_brand/model are free-text hints, not guaranteed to
    match anything in this tenant's VehicleBrand/VehicleModel catalog) plus
    the appraisal numbers, then this creates the InventoryVehicle +
    VehicleAcquisition (see services.convert_lead_to_inventory)."""

    vehicle_type = serializers.PrimaryKeyRelatedField(queryset=BodyType.objects.all())
    brand = serializers.PrimaryKeyRelatedField(queryset=VehicleBrand.objects.all())
    vehicle_model = serializers.PrimaryKeyRelatedField(queryset=VehicleModel.objects.all())
    fuel_type = serializers.PrimaryKeyRelatedField(queryset=FuelType.objects.all())
    year = serializers.IntegerField(min_value=1900, max_value=2100)
    mileage_km = serializers.IntegerField(required=False, min_value=0, default=0)
    registration_no = serializers.CharField(required=False, allow_blank=True, default="")
    listing_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)
    purchase_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    acquisition_date = serializers.DateField(required=False, allow_null=True)


class LeadStatusEventSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LeadStatusEvent
        fields = ["id", "from_status", "to_status", "note", "changed_by_name", "created_at"]

    def get_changed_by_name(self, obj):
        if obj.changed_by is None:
            return "Customer"
        try:
            return obj.changed_by.pii.get_full_name() or "Staff"
        except Exception:
            return "Staff"


class PublicLeadEnquirySerializer(serializers.Serializer):
    """Anonymous, no-auth enquiry — either about one specific vehicle (vehicle
    is injected from the URL, not accepted from the body) or a general
    search. `website` is a honeypot: real visitors never see or fill it
    (hidden via CSS on the form); any value there is treated as a bot and the
    submission is silently dropped (see public_views.py)."""

    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    enquiry_type = serializers.ChoiceField(choices=Lead.ENQUIRY_TYPE_CHOICES, required=False)
    preferred_brand = serializers.PrimaryKeyRelatedField(
        queryset=VehicleBrand.objects.all(), required=False, allow_null=True,
    )
    preferred_vehicle_type = serializers.PrimaryKeyRelatedField(
        queryset=BodyType.objects.all(), required=False, allow_null=True,
    )
    budget_min = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    budget_max = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    website = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # VehicleBrand is tenant-scoped master data — this is the one
        # anonymous, unauthenticated surface in the whole app that accepts an
        # FK pick directly from an untrusted caller, so (unlike the
        # staff-only endpoints elsewhere, which rely on queryset filtering at
        # read time rather than scoping every write FK) it's worth scoping
        # the queryset itself to the resolved tenant.
        tenant = self.context.get("tenant")
        if tenant is not None:
            self.fields["preferred_brand"].queryset = VehicleBrand.objects.filter(
                tenant=tenant, is_archived=False
            )

    def validate_full_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Name is required.")
        return name

    def validate_phone(self, value):
        phone = (value or "").strip()
        if not phone:
            raise serializers.ValidationError("Phone is required.")
        return phone
