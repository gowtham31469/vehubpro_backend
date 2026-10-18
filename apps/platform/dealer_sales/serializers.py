from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.platform.customers.models import Customer
from apps.platform.dealer_sales.models import (
    VehicleAcquisition,
    VehicleBooking,
    VehicleDelivery,
    VehicleDocument,
    VehicleNegotiation,
    VehicleOwnershipRecord,
    VehiclePriceHistory,
    VehicleReservation,
    VehicleSale,
    VehicleSaleInvoice,
    VehicleSaleInvoicePayment,
    VehicleSaleQuotation,
    VehicleSettlement,
    VehicleTimelineEvent,
    VehicleWorkExpense,
)
from apps.platform.portfolio.models import InventoryVehicle
from core.storage import StorageValidationError, delete_stored_media, resolve_media_url, upload_document_file


class VehicleAcquisitionSerializer(serializers.ModelSerializer):
    seller_customer_name = serializers.CharField(source="seller_customer.full_name", read_only=True)
    owner_customer_name = serializers.CharField(source="owner_customer.full_name", read_only=True)

    class Meta:
        model = VehicleAcquisition
        fields = [
            "id", "vehicle", "acquisition_date", "notes", "created_by",
            "seller_customer", "seller_customer_name", "seller_name", "seller_phone",
            "purchase_price", "acquisition_method", "odometer_reading", "purchase_reference",
            "owner_customer", "owner_customer_name", "agreement_reference", "owner_expected_price",
            "commission_type", "commission_value", "agreement_start_date", "agreement_end_date", "terms",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "vehicle", "created_by", "created_at", "updated_at"]

    def _effective(self, attrs, field):
        """attrs value if provided in this request, else the existing instance's value (for partial updates)."""
        if field in attrs:
            return attrs[field]
        return getattr(self.instance, field, None) if self.instance else None

    def validate(self, attrs):
        vehicle = self.context["vehicle"]
        is_owned = vehicle.inventory_type == InventoryVehicle.INVENTORY_TYPE_OWNED

        if is_owned:
            if not self._effective(attrs, "purchase_price"):
                raise serializers.ValidationError(
                    {"purchase_price": "Purchase price is required for an owned vehicle."}
                )
        else:
            if not self._effective(attrs, "owner_customer"):
                raise serializers.ValidationError(
                    {"owner_customer": "Owner is required for a consignment vehicle."}
                )
            if not self._effective(attrs, "owner_expected_price"):
                raise serializers.ValidationError(
                    {"owner_expected_price": "Owner expected price is required for a consignment vehicle."}
                )
        return attrs


class VehicleOwnershipRecordSerializer(serializers.ModelSerializer):
    owner_customer_name = serializers.CharField(source="owner_customer.full_name", read_only=True)

    class Meta:
        model = VehicleOwnershipRecord
        fields = [
            "id", "vehicle", "owner_customer", "owner_customer_name", "owner_name", "owner_type",
            "start_date", "end_date", "notes", "created_by", "created_at",
        ]
        read_only_fields = ["id", "vehicle", "created_by", "created_at"]


class VehicleWorkExpenseSerializer(serializers.ModelSerializer):
    receipt_file = serializers.FileField(write_only=True, required=False, allow_null=True)
    receipt_url = serializers.SerializerMethodField()

    class Meta:
        model = VehicleWorkExpense
        fields = [
            "id", "vehicle", "category", "description", "amount", "expense_date",
            "provider_name", "provider_type", "reference_number", "notes",
            "receipt", "receipt_file", "receipt_url", "status", "created_by",
            "is_archived", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "vehicle", "receipt", "created_by", "is_archived", "created_at", "updated_at"]

    def get_receipt_url(self, obj):
        return resolve_media_url(obj.receipt)

    def _upload_receipt(self, receipt_file, record_id):
        try:
            return upload_document_file(receipt_file, folder="dealer_vehicle_work_expenses", record_id=str(record_id))
        except StorageValidationError as exc:
            raise serializers.ValidationError({"receipt_file": str(exc)}) from None

    def create(self, validated_data):
        receipt_file = validated_data.pop("receipt_file", None)
        instance = super().create(validated_data)
        if receipt_file:
            instance.receipt = self._upload_receipt(receipt_file, instance.id)
            instance.save(update_fields=["receipt", "updated_at"])
        return instance

    def update(self, instance, validated_data):
        receipt_file = validated_data.pop("receipt_file", None)
        instance = super().update(instance, validated_data)
        if receipt_file:
            if instance.receipt:
                delete_stored_media(instance.receipt)
            instance.receipt = self._upload_receipt(receipt_file, instance.id)
            instance.save(update_fields=["receipt", "updated_at"])
        return instance


class VehiclePriceHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VehiclePriceHistory
        fields = ["id", "price_type", "old_value", "new_value", "reason", "changed_by_name", "created_at"]
        read_only_fields = fields

    def get_changed_by_name(self, obj):
        if obj.changed_by is None:
            return "System"
        try:
            return obj.changed_by.pii.get_full_name() or "Staff"
        except Exception:
            return "Staff"


class VehicleTimelineEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = VehicleTimelineEvent
        fields = ["id", "category", "title", "description", "metadata", "actor_name", "created_at"]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor is None:
            return "System"
        try:
            return obj.actor.pii.get_full_name() or "Staff"
        except Exception:
            return "Staff"


class VehicleDocumentSerializer(serializers.ModelSerializer):
    file_upload = serializers.FileField(write_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = VehicleDocument
        fields = [
            "id", "vehicle", "document_type", "file", "file_upload", "file_url",
            "notes", "uploaded_by", "created_at",
        ]
        read_only_fields = ["id", "vehicle", "file", "uploaded_by", "created_at"]

    def get_file_url(self, obj):
        return resolve_media_url(obj.file)

    def create(self, validated_data):
        file_upload = validated_data.pop("file_upload")
        instance = VehicleDocument(**validated_data)
        instance.save()
        try:
            instance.file = upload_document_file(
                file_upload, folder="dealer_vehicle_documents", record_id=str(instance.id)
            )
        except StorageValidationError as exc:
            instance.delete()
            raise serializers.ValidationError({"file_upload": str(exc)}) from None
        instance.save(update_fields=["file", "updated_at"])
        return instance


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Quotation → Negotiation → Reservation → Booking → Sale →
# Delivery → Settlement. All read-heavy; mutations go through services.py,
# so these serializers are mostly plain ModelSerializers for display plus a
# few write-input serializers for the service-function kwargs.
# ─────────────────────────────────────────────────────────────────────────


class VehicleNegotiationSerializer(serializers.ModelSerializer):
    offered_by_display = serializers.CharField(source="get_offered_by_display", read_only=True)

    class Meta:
        model = VehicleNegotiation
        fields = [
            "id", "quotation", "round_number", "offered_by", "offered_by_display",
            "amount", "notes", "created_by", "created_at",
        ]
        read_only_fields = fields


class VehicleSaleQuotationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    negotiations = VehicleNegotiationSerializer(many=True, read_only=True)

    class Meta:
        model = VehicleSaleQuotation
        fields = [
            "id", "vehicle", "customer", "customer_name", "quotation_number", "quoted_price",
            "status", "valid_until", "notes", "created_by", "negotiations",
            "sent_at", "accepted_at", "rejected_at", "rejection_reason",
            "cancelled_at", "cancellation_reason", "converted_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle", "quotation_number", "status", "created_by", "negotiations",
            "sent_at", "accepted_at", "rejected_at", "rejection_reason",
            "cancelled_at", "cancellation_reason", "converted_at",
            "created_at", "updated_at",
        ]


class VehicleReservationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)

    class Meta:
        model = VehicleReservation
        fields = [
            "id", "vehicle", "customer", "customer_name", "quotation", "reservation_date",
            "expiry_date", "deposit_amount", "status", "cancelled_at", "cancellation_reason",
            "notes", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle", "status", "cancelled_at", "cancellation_reason",
            "created_by", "created_at", "updated_at",
        ]


class VehicleBookingSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)

    class Meta:
        model = VehicleBooking
        fields = [
            "id", "vehicle", "customer", "customer_name", "reservation", "quotation",
            "booking_date", "booking_amount", "status", "cancelled_at", "cancellation_reason",
            "notes", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle", "status", "cancelled_at", "cancellation_reason",
            "created_by", "created_at", "updated_at",
        ]


class VehicleDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleDelivery
        fields = [
            "id", "sale", "delivery_date", "delivered_by", "handover_notes",
            "created_by", "created_at",
        ]
        read_only_fields = ["id", "sale", "created_by", "created_at"]


class VehicleSettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleSettlement
        fields = [
            "id", "sale", "commission_type", "commission_value", "commission_amount",
            "dealer_expenses_total", "owner_payable", "net_dealer_profit",
            "settlement_status", "settlement_date", "notes", "created_by",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class VehicleSaleSerializer(serializers.ModelSerializer):
    buyer_name = serializers.CharField(source="buyer.full_name", read_only=True)
    delivery = VehicleDeliverySerializer(read_only=True)
    settlement = VehicleSettlementSerializer(read_only=True)

    class Meta:
        model = VehicleSale
        fields = [
            "id", "vehicle", "buyer", "buyer_name", "quotation", "booking", "sale_date",
            "quoted_price", "final_sale_price", "discount_amount", "salesperson",
            "status", "cancelled_at", "cancellation_reason", "notes", "created_by",
            "delivery", "settlement", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle", "status", "cancelled_at", "cancellation_reason",
            "created_by", "delivery", "settlement", "created_at", "updated_at",
        ]


class VehicleSalesReportRowSerializer(serializers.Serializer):
    """Row shape for the Vehicle Sales Report's preview table — computes
    profit/margin via compute_sale_profit() so the report always agrees with
    the per-vehicle Profitability panel and the Insights aggregate. Read-only,
    not backed by a single model field set."""

    id = serializers.UUIDField()
    vehicle_id = serializers.CharField(source="vehicle.id")
    vehicle_label = serializers.SerializerMethodField()
    registration_no = serializers.CharField(source="vehicle.registration_no")
    inventory_type = serializers.CharField(source="vehicle.inventory_type")
    buyer_name = serializers.CharField(source="buyer.full_name")
    salesperson_name = serializers.SerializerMethodField()
    sale_date = serializers.DateField()
    final_sale_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()
    profit = serializers.SerializerMethodField()
    margin_percent = serializers.SerializerMethodField()

    def get_vehicle_label(self, obj):
        v = obj.vehicle
        return f"{v.year} {v.brand.name} {v.vehicle_model.name}"

    def get_salesperson_name(self, obj):
        if not obj.salesperson_id:
            return ""
        try:
            return obj.salesperson.pii.get_full_name() or ""
        except Exception:
            return ""

    def _profit_data(self, obj):
        from apps.platform.dealer_sales.services import compute_sale_profit
        if obj.status != VehicleSale.STATUS_CONFIRMED:
            return None
        return compute_sale_profit(obj)

    def get_profit(self, obj):
        data = self._profit_data(obj)
        return data["profit"] if data else None

    def get_margin_percent(self, obj):
        data = self._profit_data(obj)
        return data["margin_percent"] if data else None


class VehicleSaleInvoicePaymentSerializer(serializers.ModelSerializer):
    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)

    class Meta:
        model = VehicleSaleInvoicePayment
        fields = [
            "id", "invoice", "amount", "payment_mode", "payment_mode_display",
            "payment_reference", "recorded_by", "created_at",
        ]
        read_only_fields = fields


class VehicleSaleInvoiceSerializer(serializers.ModelSerializer):
    payments = VehicleSaleInvoicePaymentSerializer(many=True, read_only=True)

    class Meta:
        model = VehicleSaleInvoice
        fields = [
            "id", "sale", "invoice_number", "buyer_name_snapshot", "buyer_phone_snapshot",
            "buyer_email_snapshot", "vehicle_label_snapshot", "vehicle_registration_no_snapshot",
            "sale_amount", "payment_status", "amount_paid", "notes", "created_by",
            "payments", "issued_at", "created_at",
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 input-validation serializers (plain Serializer, not ModelSerializer)
# — views pass the validated_data straight into the matching services.py
# function as kwargs, after resolving any *_id references to instances.
# ─────────────────────────────────────────────────────────────────────────


class ReasonInputSerializer(serializers.Serializer):
    """Shared by reject/cancel endpoints — reason is always optional free text."""
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class QuotationCreateInputSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    quoted_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    valid_until = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class NegotiationCreateInputSerializer(serializers.Serializer):
    offered_by = serializers.ChoiceField(choices=VehicleNegotiation.OFFERED_BY_CHOICES)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ReservationCreateInputSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    quotation = serializers.PrimaryKeyRelatedField(
        queryset=VehicleSaleQuotation.objects.all(), required=False, allow_null=True
    )
    reservation_date = serializers.DateField()
    expiry_date = serializers.DateField(required=False, allow_null=True)
    deposit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class BookingCreateInputSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    reservation = serializers.PrimaryKeyRelatedField(
        queryset=VehicleReservation.objects.all(), required=False, allow_null=True
    )
    quotation = serializers.PrimaryKeyRelatedField(
        queryset=VehicleSaleQuotation.objects.all(), required=False, allow_null=True
    )
    booking_date = serializers.DateField()
    booking_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class SaleCreateInputSerializer(serializers.Serializer):
    buyer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    quotation = serializers.PrimaryKeyRelatedField(
        queryset=VehicleSaleQuotation.objects.all(), required=False, allow_null=True
    )
    booking = serializers.PrimaryKeyRelatedField(
        queryset=VehicleBooking.objects.all(), required=False, allow_null=True
    )
    sale_date = serializers.DateField()
    quoted_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    final_sale_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)
    salesperson = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class DeliveryCreateInputSerializer(serializers.Serializer):
    delivery_date = serializers.DateField()
    delivered_by = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True,
    )
    handover_notes = serializers.CharField(required=False, allow_blank=True, default="")


class SettlementCreateInputSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class SettlementMarkPaidInputSerializer(serializers.Serializer):
    settlement_date = serializers.DateField(required=False, allow_null=True)


class InvoiceCreateInputSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class InvoicePaymentCreateInputSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = serializers.ChoiceField(choices=VehicleSaleInvoicePayment.PAYMENT_MODE_CHOICES)
    payment_reference = serializers.CharField(required=False, allow_blank=True, default="")
