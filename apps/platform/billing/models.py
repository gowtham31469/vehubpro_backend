from django.db import models
from auditlog.registry import auditlog

from apps.common.utils.models import BaseModel, SoftArchiveModel
from apps.platform.tenants.models import Tenant


class Plan(BaseModel, SoftArchiveModel):
    BILLING_CYCLE_CHOICES = (
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    )

    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="STARTER | PRO | PORTFOLIO | FULL_PLATFORM | ENTERPRISE",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES)
    is_custom = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    max_users = models.IntegerField(default=0, help_text="Maximum number of users allowed.")
    max_vehicles = models.IntegerField(default=0, help_text="Maximum number of vehicles allowed.")

    class Meta:
        db_table = "plans"
        verbose_name = "Plan"
        verbose_name_plural = "Plans"

    def __str__(self):
        return f"{self.name} ({self.code})"


class SubscriptionLedger(BaseModel, SoftArchiveModel):
    EVENT_TYPES = (
        ("CONTRACT_STARTED", "Subscription Contract Started"),
        ("CONTRACT_RENEWED", "Subscription Contract Renewed"),
        ("CONTRACT_CANCELLED", "Subscription Contract Cancelled"),
        ("ADDON_ADDED", "Add-on Added"),
        ("ADDON_REMOVED", "Add-on Removed"),
        ("LIMIT_OVERRIDDEN", "User Limit Overridden"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="billing_ledger")
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    payload = models.JSONField(help_text="Snapshot of the change details")
    effective_at = models.DateTimeField(help_text="When this change takes effect")
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="billing_actions",
    )

    class Meta:
        db_table = "subscription_ledger"
        ordering = ["-effective_at", "-created_at"]

    def __str__(self):
        return f"{self.tenant.name} - {self.event_type} ({self.effective_at})"


class TenantSubscription(BaseModel, SoftArchiveModel):
    BILLING_CYCLE_CHOICES = (
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    )
    STATUS_CHOICES = (
        ("active", "Active"),
        ("trial", "Trial"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions", null=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    max_users = models.IntegerField(
        default=0,
        help_text="Maximum number of users allowed. Defaults to Plan's max_users but can be overridden.",
    )
    max_vehicles = models.IntegerField(
        default=0,
        help_text="Maximum number of vehicles allowed. Defaults to Plan's max_vehicles but can be overridden.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="trial")
    ledger_entry = models.ForeignKey(
        SubscriptionLedger,
        on_delete=models.PROTECT,
        null=True,
        related_name="resulting_subscriptions",
        help_text="The ledger entry that created or last modified this subscription record",
    )

    class Meta:
        db_table = "tenant_subscriptions"
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"{self.tenant.name} - {self.plan.name if self.plan else 'No Plan'} ({self.status})"


class SubscriptionAddOn(BaseModel, SoftArchiveModel):
    ADDON_TYPES = (
        ("USERS", "Extra Users"),
        ("VEHICLES", "Extra Vehicles"),
        ("STORAGE", "Extra Storage"),
        ("LOCATIONS", "Extra Locations"),
        ("FEATURES", "Premium Features"),
    )

    subscription = models.ForeignKey(TenantSubscription, on_delete=models.CASCADE, related_name="addons")
    ledger_entry = models.ForeignKey(
        SubscriptionLedger, on_delete=models.PROTECT, related_name="resulting_addons"
    )
    type = models.CharField(max_length=20, choices=ADDON_TYPES)
    users_quantity = models.PositiveIntegerField(
        default=0, help_text="Number of users added by this addon."
    )
    vehicles_quantity = models.PositiveIntegerField(
        default=0, help_text="Number of vehicles added by this addon."
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "subscription_addons"

    def __str__(self):
        qty = self.users_quantity if self.type == "USERS" else self.vehicles_quantity
        return f"{self.subscription.tenant.name} - {self.type} (+{qty})"


class SubscriptionHistory(BaseModel, SoftArchiveModel):
    BILLING_CYCLE_CHOICES = (
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="subscription_history")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, related_name="subscription_history")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    max_users = models.IntegerField(
        default=0,
        help_text="Maximum number of users allowed at the time of this history record.",
    )
    max_vehicles = models.IntegerField(
        default=0,
        help_text="Maximum number of vehicles allowed at the time of this history record.",
    )
    change_reason = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Reason for the subscription change",
    )

    class Meta:
        db_table = "subscription_history"

    def __str__(self):
        return f"History: {self.tenant.name} - {self.plan.name if self.plan else 'No Plan'}"


auditlog.register(Plan)
auditlog.register(SubscriptionLedger)
auditlog.register(TenantSubscription)
auditlog.register(SubscriptionAddOn)
auditlog.register(SubscriptionHistory)
