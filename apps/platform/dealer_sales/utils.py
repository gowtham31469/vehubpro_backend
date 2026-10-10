from django.db import transaction

from apps.platform.dealer_sales.models import DealerQuotationFySequence, DealerSaleInvoiceFySequence
from apps.platform.jobcards.models import indian_fy_code


def allocate_next_dealer_quotation_number(tenant_id) -> str:
    """Thread-safe next number: DQ/{FY}/{5d}, mirroring
    apps.platform.quotations.utils.allocate_next_quotation_number."""
    fy = indian_fy_code()
    with transaction.atomic():
        row, _ = DealerQuotationFySequence.objects.select_for_update().get_or_create(
            tenant_id=tenant_id, fy_code=fy, defaults={"last_seq": 0},
        )
        row.last_seq += 1
        row.save(update_fields=["last_seq", "updated_at"])
        return f"DQ/{fy}/{row.last_seq:05d}"


def allocate_next_dealer_sale_invoice_number(tenant_id) -> str:
    """Thread-safe next number: DSI/{FY}/{5d}."""
    fy = indian_fy_code()
    with transaction.atomic():
        row, _ = DealerSaleInvoiceFySequence.objects.select_for_update().get_or_create(
            tenant_id=tenant_id, fy_code=fy, defaults={"last_seq": 0},
        )
        row.last_seq += 1
        row.save(update_fields=["last_seq", "updated_at"])
        return f"DSI/{fy}/{row.last_seq:05d}"
