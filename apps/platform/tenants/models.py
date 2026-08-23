from django.db import models

from apps.common.encryption.pii import encryptor
from apps.common.utils.models import BaseModel, SoftArchiveModel


class Tenant(BaseModel, SoftArchiveModel):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("suspended", "Suspended"),
        ("cancelled", "Cancelled"),
    ]

    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    onboarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants"

    def __str__(self) -> str:
        return self.name


class TenantBranding(BaseModel):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="branding")
    logo = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text="Relative path under MEDIA (LOCAL) or S3 object key.",
    )
    dark_logo = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text="Relative path under MEDIA (LOCAL) or S3 object key.",
    )
    favicon = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text="Relative path under MEDIA (LOCAL) or S3 object key.",
    )
    primary_color = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        db_table = "tenant_branding"

    def __str__(self) -> str:
        return f"Branding for {self.tenant.name}"


class TenantPII(BaseModel):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="pii")

    gstin_encrypted = models.TextField(null=True, blank=True)
    gstin_key_version = models.CharField(max_length=16, blank=True, default="")
    gstin_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    address = models.TextField(null=True, blank=True)

    contact_name_encrypted = models.TextField(null=True, blank=True)
    contact_name_key_version = models.CharField(max_length=16, blank=True, default="")
    email_encrypted = models.TextField(null=True, blank=True)
    email_key_version = models.CharField(max_length=16, blank=True, default="")
    phone_encrypted = models.TextField(null=True, blank=True)
    phone_key_version = models.CharField(max_length=16, blank=True, default="")
    alternate_phone_encrypted = models.TextField(null=True, blank=True)
    alternate_phone_key_version = models.CharField(max_length=16, blank=True, default="")

    is_anonymized = models.BooleanField(default=False)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenant_pii"

    def __str__(self) -> str:
        return f"PII for {self.tenant.name}"

    def set_gstin(self, value: str) -> None:
        self.gstin_encrypted, self.gstin_key_version = encryptor.encrypt(value)
        self.gstin_hash = encryptor.hash_value(value)

    def get_gstin(self) -> str:
        return encryptor.decrypt(self.gstin_encrypted, self.gstin_key_version)

    def set_contact_name(self, value: str) -> None:
        self.contact_name_encrypted, self.contact_name_key_version = encryptor.encrypt(value)

    def get_contact_name(self) -> str:
        return encryptor.decrypt(self.contact_name_encrypted, self.contact_name_key_version)

    def set_email(self, value: str) -> None:
        self.email_encrypted, self.email_key_version = encryptor.encrypt(value)

    def get_email(self) -> str:
        return encryptor.decrypt(self.email_encrypted, self.email_key_version)

    def set_phone(self, value: str) -> None:
        self.phone_encrypted, self.phone_key_version = encryptor.encrypt(value)

    def get_phone(self) -> str:
        return encryptor.decrypt(self.phone_encrypted, self.phone_key_version)

    def set_alternate_phone(self, value: str) -> None:
        self.alternate_phone_encrypted, self.alternate_phone_key_version = encryptor.encrypt(value)

    def get_alternate_phone(self) -> str:
        return encryptor.decrypt(self.alternate_phone_encrypted, self.alternate_phone_key_version)


class TenantInvoiceSettings(BaseModel):
    """Bank account details, UPI QR code, and terms & conditions printed on invoice/job-card PDFs."""

    ACCOUNT_TYPE_CHOICES = [
        ("savings", "Savings"),
        ("current", "Current"),
    ]

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="invoice_settings")

    account_holder_name = models.CharField(max_length=255, blank=True, default="")
    account_number_encrypted = models.TextField(null=True, blank=True)
    account_number_key_version = models.CharField(max_length=16, blank=True, default="")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, blank=True, default="")
    ifsc_code = models.CharField(max_length=20, blank=True, default="")
    bank_name = models.CharField(max_length=255, blank=True, default="")
    branch_name = models.CharField(max_length=255, blank=True, default="")
    upi_id = models.CharField(max_length=255, blank=True, default="")
    qr_code = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text="Relative path under MEDIA (LOCAL) or S3 object key.",
    )
    terms_and_conditions = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Supports {{tenant_name}}, {{advance_payment_percentage}}, {{estimate_charge_percentage}}, "
            "{{replaced_parts_retention_days}}, {{service_warranty_days}}, {{currency_symbol}} placeholders — "
            "substituted with the values below when rendering the PDF."
        ),
    )
    show_terms_and_conditions = models.BooleanField(
        default=True,
        help_text="When off, the Terms & Conditions section is omitted from invoice PDFs regardless of the text above.",
    )

    # ── Terms & conditions template variables ────────────────────────────
    currency_symbol = models.CharField(max_length=5, blank=True, default="₹")
    advance_payment_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    estimate_charge_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=3)
    replaced_parts_retention_days = models.PositiveSmallIntegerField(default=2)
    service_warranty_days = models.PositiveSmallIntegerField(default=30)

    class Meta:
        db_table = "tenant_invoice_settings"

    def __str__(self) -> str:
        return f"Invoice settings for {self.tenant.name}"

    def set_account_number(self, value: str) -> None:
        self.account_number_encrypted, self.account_number_key_version = encryptor.encrypt(value)

    def get_account_number(self) -> str:
        return encryptor.decrypt(self.account_number_encrypted, self.account_number_key_version)

    def render_terms_and_conditions(self) -> str:
        """Substitute {{variable}} placeholders in terms_and_conditions with this tenant's values."""
        import re
        from decimal import Decimal

        if not self.terms_and_conditions:
            return ""

        def _fmt(value):
            if isinstance(value, Decimal):
                return f"{value.normalize():f}" if value == value.to_integral_value() else f"{value:f}"
            return str(value)

        variables = {
            "tenant_name": self.tenant.name if self.tenant_id else "",
            "advance_payment_percentage": _fmt(self.advance_payment_percentage),
            "estimate_charge_percentage": _fmt(self.estimate_charge_percentage),
            "replaced_parts_retention_days": self.replaced_parts_retention_days,
            "service_warranty_days": self.service_warranty_days,
            "currency_symbol": self.currency_symbol,
        }

        def _sub(match):
            key = match.group(1).strip()
            value = variables.get(key)
            return str(value) if value is not None else match.group(0)

        return re.sub(r"\{\{\s*(\w+)\s*\}\}", _sub, self.terms_and_conditions)
