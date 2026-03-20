"""Custom user and encrypted PII models."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q

from apps.common.encryption.pii import encryptor
from apps.common.utils.models import BaseModel, SoftArchiveModel


class UserManager(BaseUserManager):
    """Manager for custom UUID-based user model."""

    def create_user(self, password: str | None = None, **extra_fields):
        user = self.model(**extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("status", User.Status.ACTIVE)
        return self.create_user(password=password, **extra_fields)


class User(BaseModel, SoftArchiveModel, AbstractBaseUser, PermissionsMixin):
    """SaaS-friendly user model."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    role = models.ForeignKey(
        "masters.Role",
        on_delete=models.SET_NULL,
        related_name="users",
        null=True,
        blank=True,
        db_index=True,
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
        db_index=True,
    )
    is_first_time_user = models.BooleanField(default=True)

    # Required for Django auth/admin interoperability.
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = UserManager()

    USERNAME_FIELD = "id"
    REQUIRED_FIELDS = []

    def __str__(self) -> str:
        return str(self.id)

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]


class UserPII(BaseModel):
    """Encrypted PII storage with key-version tracking and rotation support."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pii")

    email_hash = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)

    email_encrypted = models.TextField(null=True, blank=True)
    email_key_version = models.CharField(max_length=16, blank=True, default="")

    phone_encrypted = models.TextField(null=True, blank=True)
    phone_key_version = models.CharField(max_length=16, blank=True, default="")

    full_name_encrypted = models.TextField(null=True, blank=True)
    full_name_key_version = models.CharField(max_length=16, blank=True, default="")

    is_anonymized = models.BooleanField(default=False)
    anonymized_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return f"PII for {self.user_id}"

    def set_email(self, email: str) -> None:
        self.email_hash = encryptor.hash_value(email)
        self.email_encrypted, self.email_key_version = encryptor.encrypt(email)

    def get_email(self) -> str:
        return encryptor.decrypt(self.email_encrypted, self.email_key_version)

    def set_phone(self, phone: str) -> None:
        self.phone_encrypted, self.phone_key_version = encryptor.encrypt(phone)

    def get_phone(self) -> str:
        return encryptor.decrypt(self.phone_encrypted, self.phone_key_version)

    def set_full_name(self, name: str) -> None:
        self.full_name_encrypted, self.full_name_key_version = encryptor.encrypt(name)

    def get_full_name(self) -> str:
        return encryptor.decrypt(self.full_name_encrypted, self.full_name_key_version)

    def rotate_keys(self) -> None:
        """Re-encrypt all stored PII to the active key version."""
        changed = False
        active = encryptor.active_version

        if self.email_encrypted and self.email_key_version and self.email_key_version != active:
            self.email_encrypted, self.email_key_version = encryptor.rotate(
                self.email_encrypted, self.email_key_version
            )
            changed = True
        if self.phone_encrypted and self.phone_key_version and self.phone_key_version != active:
            self.phone_encrypted, self.phone_key_version = encryptor.rotate(
                self.phone_encrypted, self.phone_key_version
            )
            changed = True
        if (
            self.full_name_encrypted
            and self.full_name_key_version
            and self.full_name_key_version != active
        ):
            self.full_name_encrypted, self.full_name_key_version = encryptor.rotate(
                self.full_name_encrypted, self.full_name_key_version
            )
            changed = True

        if changed:
            self.save(
                update_fields=[
                    "email_encrypted",
                    "email_key_version",
                    "phone_encrypted",
                    "phone_key_version",
                    "full_name_encrypted",
                    "full_name_key_version",
                    "updated_at",
                ]
            )

    class Meta:
        db_table = "user_pii"


class UserFCMToken(BaseModel):
    """Device-level FCM token storage for push notifications."""

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    class App(models.TextChoices):
        PLATFORM = "platform", "Platform"
        PORTAL = "portal", "Portal"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fcm_tokens",
        db_index=True,
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="fcm_tokens",
        null=True,
        blank=True,
        db_index=True,
    )
    fcm_token = models.TextField(unique=True, db_index=True)
    device_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    app = models.CharField(max_length=20, choices=App.choices, default=App.PORTAL, db_index=True)
    platform = models.CharField(max_length=20, choices=Platform.choices)
    is_active = models.BooleanField(default=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_fcm_tokens"
        indexes = [
            models.Index(fields=["user", "device_id", "app"], name="fcm_user_device_app_idx"),
            models.Index(fields=["tenant", "user"], name="fcm_tenant_user_idx"),
            models.Index(fields=["is_active", "last_used_at"], name="fcm_active_used_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_id", "app"],
                condition=Q(device_id__isnull=False),
                name="fcm_unique_user_device_app",
            ),
        ]
