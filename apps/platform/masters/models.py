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


class State(BaseModel):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=12, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "states"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class City(BaseModel):
    state = models.ForeignKey("masters.State", on_delete=models.CASCADE, related_name="cities")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cities"
        ordering = ["name"]
        unique_together = ("state", "name")
        indexes = [
            models.Index(fields=["state", "name"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.state.name}"
