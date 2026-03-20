"""Common abstract models for consistency across apps."""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class BaseModel(models.Model):
    """Base model with UUID primary key and audit timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftArchiveModel(models.Model):
    """Soft archive scaffold to support data lifecycle controls."""

    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    def archive(self) -> None:
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=["is_archived", "archived_at", "updated_at"])

    class Meta:
        abstract = True
