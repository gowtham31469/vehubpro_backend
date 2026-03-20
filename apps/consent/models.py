from __future__ import annotations

from django.db import models
from auditlog.registry import auditlog

from apps.common.utils.models import BaseModel


class DataSubject(BaseModel):
    class SubjectType(models.TextChoices):
        PLATFORM_USER = "platform_user", "Platform User"
        TENANT_ADMIN = "tenant_admin", "Tenant Admin"
        TENANT_USER = "tenant_user", "Tenant User"
        CLIENT_EMPLOYEE = "client_employee", "Client Employee"
        VISITOR = "visitor", "Visitor"
        OPSTRACK_STAFF = "opstrack_staff", "Opstrack Staff"

    subject_type = models.CharField(max_length=20, choices=SubjectType.choices)
    subject_id = models.UUIDField()

    class Meta:
        db_table = "data_subjects"
        constraints = [
            models.UniqueConstraint(fields=["subject_type", "subject_id"], name="uq_data_subject_type_id")
        ]
        indexes = [
            models.Index(fields=["subject_type", "subject_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject_type} - {self.subject_id}"


class ConsentType(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(null=True, blank=True)
    retention_days = models.IntegerField(null=True, blank=True)
    is_mandatory = models.BooleanField(default=False)

    class Meta:
        db_table = "consent_types"

    def __str__(self) -> str:
        return self.code


class Consent(BaseModel):
    class Status(models.TextChoices):
        GRANTED = "granted", "Granted"
        WITHDRAWN = "withdrawn", "Withdrawn"
        EXPIRED = "expired", "Expired"

    class Source(models.TextChoices):
        WEB_APP = "web_app", "Web Application"
        MOBILE_APP = "mobile_app", "Mobile Application"
        ADMIN_PANEL = "admin_panel", "Admin Panel"
        PUBLIC_API = "public_api", "Public API"
        CONTRACT = "contract", "Contract Document"
        COOKIE_BANNER = "cookie_banner", "Cookie Banner"
        KIOSK = "kiosk", "Visitor Kiosk"
        IMPORT = "import", "Data Import"
        SYSTEM = "system", "System Generated"

    data_subject = models.ForeignKey(DataSubject, on_delete=models.CASCADE, related_name="consents")
    consent_type = models.ForeignKey(ConsentType, on_delete=models.CASCADE, related_name="consents")
    status = models.CharField(max_length=20, choices=Status.choices)
    granted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices)
    policy_version = models.CharField(max_length=50, null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "consents"
        indexes = [
            models.Index(fields=["data_subject", "consent_type"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.data_subject} - {self.consent_type} ({self.status})"


class ConsentHistory(BaseModel):
    class Status(models.TextChoices):
        GRANTED = "granted", "Granted"
        WITHDRAWN = "withdrawn", "Withdrawn"
        EXPIRED = "expired", "Expired"

    consent = models.ForeignKey(Consent, on_delete=models.CASCADE, related_name="history")
    old_status = models.CharField(max_length=20, choices=Status.choices, null=True, blank=True)
    new_status = models.CharField(max_length=20, choices=Status.choices)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.UUIDField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "consent_history"

    def __str__(self) -> str:
        return f"History: {self.consent_id} -> {self.new_status}"


auditlog.register(ConsentType)
auditlog.register(Consent)
