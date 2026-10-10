from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.common.encryption.pii import encryptor
from apps.platform.customers.models import Customer
from apps.platform.masters.models import Role
from apps.platform.modules.models import UserSubmodulePermission
from apps.platform.notifications.models import Notification
from apps.platform.portfolio.models import VisitRequest, VisitRequestStatusEvent
from apps.platform.users.models import User, UserPII


class CustomerSignupSerializer(serializers.Serializer):
    """
    Creates a customer-facing User + UserPII identity for the tenant resolved
    from the storefront subdomain, and links it to (or creates) the matching
    CRM Customer row. Email uniqueness is scoped per tenant (see
    UserPII.is_customer_identity) — the same email may sign up separately at
    different tenants' storefronts.
    """

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        value = value.strip().lower()
        email_hash = encryptor.hash_value(value)
        tenant = self.context["tenant"]
        exists = UserPII.objects.filter(
            email_hash=email_hash, tenant=tenant, is_customer_identity=True
        ).exists()
        if exists:
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    @transaction.atomic
    def save(self):
        tenant = self.context["tenant"]
        full_name = self.validated_data["full_name"]
        email = self.validated_data["email"]
        phone = self.validated_data["phone"]
        password = self.validated_data["password"]

        role = Role.objects.get(code="CUSTOMER")
        user = User.objects.create_user(
            password=password,
            role=role,
            tenant=tenant,
            is_staff=False,
            status=User.Status.ACTIVE,
        )

        pii = UserPII(user=user, tenant=tenant, is_customer_identity=True)
        pii.set_full_name(full_name)
        pii.set_email(email)
        pii.set_phone(phone)
        pii.save()

        customer = Customer.objects.filter(tenant=tenant, phone=phone, user__isnull=True).first()
        if customer is not None:
            customer.user = user
            customer.save(update_fields=["user", "updated_at"])
        else:
            Customer.objects.create(
                tenant=tenant, full_name=full_name, email=email, phone=phone, user=user
            )

        return user


class CustomerLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        email = attrs.get("email", "").strip().lower()
        password = attrs.get("password")

        email_hash = encryptor.hash_value(email)
        pii = (
            UserPII.objects.select_related("user")
            .filter(
                email_hash=email_hash,
                tenant=tenant,
                is_customer_identity=True,
                is_anonymized=False,
            )
            .first()
        )
        if not pii or not pii.user:
            raise serializers.ValidationError("Invalid email or password.")

        user = pii.user
        if not user.check_password(password):
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("User account is inactive.")

        attrs["user"] = user
        attrs["email"] = email
        return attrs


class ProfileSerializer(serializers.Serializer):
    """
    Read/update a customer's own profile. Deliberately exposes email/phone as
    read-only display fields only — full_name is the only writable field.
    Email is the login identity and must never change here.
    """

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(read_only=True)
    phone = serializers.CharField(read_only=True)

    def to_representation(self, user):
        pii = getattr(user, "pii", None)
        return {
            "full_name": pii.get_full_name() if pii else "",
            "email": pii.get_email() if pii else "",
            "phone": pii.get_phone() if pii else "",
        }

    def update(self, user, validated_data):
        pii = user.pii
        pii.set_full_name(validated_data["full_name"])
        pii.save(update_fields=["full_name_encrypted", "full_name_key_version", "updated_at"])
        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        user = self.context["user"]
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        try:
            validate_password(value, user=self.context["user"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def save(self):
        user = self.context["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user


class VisitRequestCreateSerializer(serializers.Serializer):
    """Creates a VisitRequest for the logged-in customer + a specific vehicle.
    One request per (customer, vehicle), permanently — see VisitRequest.Meta.constraints."""

    preferred_date = serializers.DateField(required=False, allow_null=True)
    preferred_time = serializers.TimeField(required=False, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_preferred_date(self, value):
        if value and value < timezone.localdate():
            raise serializers.ValidationError("Preferred date can't be in the past.")
        return value

    def validate(self, attrs):
        user = self.context["user"]
        vehicle = self.context["vehicle"]
        if VisitRequest.objects.filter(customer_user=user, vehicle=vehicle).exists():
            raise serializers.ValidationError("You've already requested a visit for this vehicle.")
        return attrs

    @transaction.atomic
    def save(self):
        user = self.context["user"]
        vehicle = self.context["vehicle"]
        tenant = user.tenant
        pii = user.pii
        message = self.validated_data.get("message") or ""

        visit_request = VisitRequest.objects.create(
            tenant=tenant,
            vehicle=vehicle,
            customer_user=user,
            full_name=pii.get_full_name() or "",
            phone=pii.get_phone() or "",
            email=pii.get_email() or "",
            preferred_date=self.validated_data.get("preferred_date"),
            preferred_time=self.validated_data.get("preferred_time"),
            message=message,
        )

        VisitRequestStatusEvent.objects.create(
            visit_request=visit_request,
            from_status=None,
            to_status=VisitRequest.STATUS_PENDING,
            note=message,
            changed_by=None,
        )

        recipient_ids = (
            UserSubmodulePermission.objects.filter(
                tenant=tenant,
                is_active=True,
                user__is_archived=False,
                submodule_permission__submodule__key="visit_requests",
                submodule_permission__permission__key="view",
            )
            .values_list("user_id", flat=True)
            .distinct()
        )
        vehicle_label = f"{vehicle.year} {vehicle.brand.name} {vehicle.vehicle_model.name}"
        Notification.objects.bulk_create(
            [
                Notification(
                    tenant=tenant,
                    user_id=recipient_id,
                    title="New visit request",
                    message=f"{visit_request.full_name} requested a visit for the {vehicle_label}.",
                    link="/admin/portfolio/visit-requests",
                )
                for recipient_id in recipient_ids
            ]
        )

        return visit_request
