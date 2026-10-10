from django.conf import settings
from django.db import models

from apps.common.utils.models import BaseModel


class WishlistItem(BaseModel):
    """A customer's saved inventory vehicle. Inventory only — Services aren't wishlist-able."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist_items"
    )
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="wishlisted_by"
    )

    class Meta:
        db_table = "portal_wishlist_items"
        constraints = [
            models.UniqueConstraint(fields=["user", "vehicle"], name="uniq_wishlist_user_vehicle"),
        ]
