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
