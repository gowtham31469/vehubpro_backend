from django.db import models

from apps.common.utils.models import BaseModel, SoftArchiveModel


class Role(BaseModel, SoftArchiveModel):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "roles"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
