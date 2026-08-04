"""
InvoiceService — core business logic for converting a JobCard into an Invoice.

Design principles
-----------------
1. Atomicity: the entire generation (sequence allocation + Invoice row + line item rows +
   JobCard status update) happens inside a single DB transaction. A failure at any step
   leaves no partial invoice.

2. Immutability: financial totals are copied from the JobCard at the moment of generation
   and are never recalculated afterward. This satisfies GST record-keeping requirements.

3. PII isolation: customer PII is re-encrypted into invoice-level snapshot columns so that
   the customer record can later be erased (DPDP / GDPR) without breaking invoice integrity.
   Only the PII columns are erased; financial totals remain for statutory compliance.

4. Idempotency guard: attempting to generate an invoice for a job card that already has one
   raises InvoiceAlreadyExists. Callers should check for this and return HTTP 409.

5. Status gate: only job cards with status == 'completed' can be invoiced. Enforced here,
   not just in the view layer.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction, models
from django.utils import timezone

from apps.common.encryption.pii import encryptor
from apps.platform.invoices.models import Invoice, InvoiceFySequence, InvoiceLineItem, InvoicePayment
from apps.platform.jobcards.models import JobCard, indian_fy_code


class InvoiceError(Exception):
    """Base class for InvoiceService errors."""


class InvoiceAlreadyExists(InvoiceError):
    """Raised when a job card already has an invoice."""


class InvalidJobCardStatus(InvoiceError):
    """Raised when the job card is not in the 'completed' state."""


def _allocate_invoice_number(tenant_id) -> tuple[str, str, int]:
    """
    Thread-safe invoice number allocation inside an atomic block.
    Returns (invoice_number, fy_code, sequence_no).
    Must be called within an active transaction.atomic() context.
    """
    fy = indian_fy_code(timezone.now().date())
    row, _ = InvoiceFySequence.objects.select_for_update().get_or_create(
        tenant_id=tenant_id,
        fy_code=fy,
        defaults={"last_seq": 0},
    )
    row.last_seq += 1
    row.save(update_fields=["last_seq", "updated_at"])
    invoice_number = f"INV/{fy}/{row.last_seq:05d}"
    return invoice_number, fy, row.last_seq


def _encrypt_pii(value: str | None) -> tuple[str, str]:
    """Encrypt a PII string and return (encrypted_token, key_version). Returns ('', '') for falsy."""
    if not value:
        return "", ""
    encrypted, key_version = encryptor.encrypt(str(value).strip())
    return encrypted, key_version


def _build_customer_address(customer) -> str:
    """Assemble a single address string from customer fields (non-PII parts omitted)."""
    parts = []
    if customer.address:
        parts.append(customer.address.strip())
    city_name = getattr(customer.city, "name", None) if customer.city_id else None
    state_name = getattr(customer.state, "name", None) if customer.state_id else None
    if city_name:
        parts.append(city_name)
    if state_name:
        parts.append(state_name)
    if customer.postal_code:
        parts.append(customer.postal_code.strip())
    return ", ".join(filter(None, parts))


def _build_vehicle_label(vehicle) -> str:
    brand = getattr(vehicle.brand, "name", "") if vehicle.brand_id else ""
    model = getattr(vehicle.vehicle_model, "name", "") if vehicle.vehicle_model_id else ""
    year = vehicle.year or ""
    return f"{brand} {model} ({year})".strip()


def _snapshot_tenant(tenant) -> dict:
    """Return plaintext statutory tenant fields for the invoice snapshot."""
    gstin = ""
    address = ""
    try:
        pii = tenant.pii
        gstin = pii.get_gstin() if pii.gstin_encrypted else ""
        address = pii.address or ""
    except Exception:
        pass
    return {
        "tenant_name_snapshot": tenant.name or "",
        "tenant_gstin_snapshot": gstin,
        "tenant_address_snapshot": address,
    }


class InvoiceService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    @transaction.atomic
    def generate(job_card: JobCard, issued_by) -> Invoice:
        """
        Convert a completed JobCard into an immutable GST Invoice.

        Parameters
        ----------
        job_card : JobCard
            Must be in 'completed' status and must not already have an invoice.
        issued_by : User
            The authenticated user triggering the generation (logged as invoice issuer).

        Returns
        -------
        Invoice
            The freshly created Invoice instance with all line items populated.

        Raises
        ------
        InvalidJobCardStatus
            If job_card.status != 'completed'.
        InvoiceAlreadyExists
            If an Invoice already exists for this job card.
        """
        # ── Status gate ───────────────────────────────────────────────────────
        if job_card.status != JobCard.STATUS_COMPLETED:
            raise InvalidJobCardStatus(
                f"Job card '{job_card.jobcard_number}' must be in 'completed' status "
                f"before generating an invoice (current: '{job_card.status}')."
            )

        # ── Idempotency guard ─────────────────────────────────────────────────
        if Invoice.objects.filter(job_card=job_card).exists():
            raise InvoiceAlreadyExists(
                f"An invoice already exists for job card '{job_card.jobcard_number}'."
            )

        # ── Prefetch related objects needed for snapshots ─────────────────────
        customer = job_card.customer
        # Eagerly load related fields that may not be pre-fetched
        if not hasattr(customer, "_state") or customer.city_id and not hasattr(customer, "_city_cache"):
            from apps.platform.customers.models import Customer
            customer = Customer.objects.select_related("state", "city").get(pk=customer.pk)

        vehicle = job_card.vehicle
        tenant = job_card.tenant

        # ── Allocate invoice number (sequence locked) ─────────────────────────
        invoice_number, fy_code, sequence_no = _allocate_invoice_number(job_card.tenant_id)

        # ── Encrypt customer PII snapshot ─────────────────────────────────────
        name_enc, name_kv = _encrypt_pii(customer.full_name)
        phone_enc, phone_kv = _encrypt_pii(customer.phone)
        email_enc, email_kv = _encrypt_pii(customer.email)
        address_enc, address_kv = _encrypt_pii(_build_customer_address(customer))

        # ── Tenant statutory snapshot ─────────────────────────────────────────
        tenant_fields = _snapshot_tenant(tenant)

        # ── Vehicle snapshot (non-PII) ────────────────────────────────────────
        vehicle_label = _build_vehicle_label(vehicle)
        reg_no = vehicle.registration_no or ""
        vin_no = getattr(vehicle, "vin_number", "") or ""
        km_reading = getattr(job_card, "km_reading", None)
        vehicle_brand_name = getattr(vehicle.brand, "name", "") if vehicle.brand_id else ""
        vehicle_model_name = getattr(vehicle.vehicle_model, "name", "") if vehicle.vehicle_model_id else ""
        vehicle_engine_no = getattr(vehicle, "engine_number", "") or ""
        vehicle_year = getattr(vehicle, "year", None)

        # ── Create Invoice header ─────────────────────────────────────────────
        invoice = Invoice.objects.create(
            tenant=tenant,
            job_card=job_card,
            invoice_number=invoice_number,
            fy_code=fy_code,
            sequence_no=sequence_no,
            issued_by=issued_by,
            # PII snapshots
            customer_name_encrypted=name_enc,
            customer_name_key_version=name_kv,
            customer_phone_encrypted=phone_enc,
            customer_phone_key_version=phone_kv,
            customer_email_encrypted=email_enc,
            customer_email_key_version=email_kv,
            customer_address_encrypted=address_enc,
            customer_address_key_version=address_kv,
            customer_gstin=getattr(customer, "gstin", None) or None,
            # Tenant snapshot
            **tenant_fields,
            # Vehicle snapshot
            vehicle_registration_no_snapshot=reg_no,
            vehicle_label_snapshot=vehicle_label,
            vehicle_vin_snapshot=vin_no,
            vehicle_odometer_snapshot=km_reading,
            vehicle_brand_snapshot=vehicle_brand_name,
            vehicle_model_snapshot=vehicle_model_name,
            vehicle_engine_no_snapshot=vehicle_engine_no,
            vehicle_year_snapshot=vehicle_year,
            # Financial totals (copied verbatim — immutable after this point)
            subtotal=job_card.subtotal,
            discount_amount=job_card.discount_amount,
            shop_fees=job_card.shop_fees,
            cgst_amount=job_card.cgst_amount,
            sgst_amount=job_card.sgst_amount,
            igst_amount=job_card.igst_amount,
            total_amount=job_card.total_amount,
            # Carry over next service recommendation from job card
            next_service_recommendation=getattr(job_card, "next_service_recommendation", "") or "",
            # Payment — starts unpaid
            payment_status=Invoice.PAYMENT_STATUS_UNPAID,
            amount_paid=Decimal("0.00"),
        )

        # ── Snapshot line items ───────────────────────────────────────────────
        line_items_data = list(
            job_card.line_items.select_related("service_item")
            .order_by("sort_order", "created_at")
        )
        invoice_lines = []
        for line in line_items_data:
            hsn_sac = ""
            if line.service_item_id and line.service_item:
                hsn_sac = line.service_item.hsn_code or ""
            invoice_lines.append(
                InvoiceLineItem(
                    invoice=invoice,
                    sort_order=line.sort_order,
                    service_type=line.service_type,
                    description=line.description,
                    detail_text=line.detail_text or "",
                    hsn_sac_code=hsn_sac,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_amount=line.discount_amount,
                    gst_percentage=line.gst_percentage,
                    cgst_amount=line.cgst_amount,
                    sgst_amount=line.sgst_amount,
                    line_total=line.line_total,
                )
            )
        InvoiceLineItem.objects.bulk_create(invoice_lines)

        # ── Advance job card status → invoiced ───────────────────────────────
        JobCard.objects.filter(pk=job_card.pk).update(
            status=JobCard.STATUS_INVOICED,
            updated_at=timezone.now(),
        )

        return invoice

    @staticmethod
    @transaction.atomic
    def record_payment(invoice: Invoice, *, payment_mode: str, amount_paid: Decimal,
                       payment_reference: str = "", recorded_by) -> Invoice:
        """
        Record an additional payment against an invoice.

        Derives payment_status automatically by aggregating all payments:
          - sum == 0                  → unpaid
          - 0 < sum < total_amount    → partial
          - sum >= total_amount       → paid
        """
        amount_paid = Decimal(str(amount_paid or 0)).quantize(Decimal("0.01"))
        
        if amount_paid > 0:
            InvoicePayment.objects.create(
                invoice=invoice,
                amount=amount_paid,
                payment_mode=payment_mode,
                payment_reference=payment_reference,
                recorded_by=recorded_by,
            )

        sum_paid = InvoicePayment.objects.filter(invoice=invoice).aggregate(
            total=models.Sum("amount")
        )["total"] or Decimal("0")
        
        total = Decimal(str(invoice.total_amount))

        if sum_paid <= 0:
            new_status = Invoice.PAYMENT_STATUS_UNPAID
        elif sum_paid >= total:
            new_status = Invoice.PAYMENT_STATUS_PAID
        else:
            new_status = Invoice.PAYMENT_STATUS_PARTIAL

        Invoice.objects.filter(pk=invoice.pk).update(
            payment_status=new_status,
            amount_paid=sum_paid,
            updated_at=timezone.now(),
        )
        invoice.refresh_from_db()
        return invoice

    @staticmethod
    @transaction.atomic
    def erase_customer_pii(invoice: Invoice) -> Invoice:
        """
        Null all customer PII snapshot fields.
        Financial totals are untouched (GST compliance).
        Called from the platform-level DPDP / GDPR erasure workflow.

        Also deletes the stored PDF (which contains baked-in PII) and nulls
        pdf_key so the file is no longer referenced by any URL.
        """
        # Delete stored PDF before nulling the key — erase_pii() nulls pdf_key
        old_pdf_key = invoice.pdf_key
        invoice.erase_pii()
        invoice.save(update_fields=[
            "customer_name_encrypted", "customer_name_key_version",
            "customer_phone_encrypted", "customer_phone_key_version",
            "customer_email_encrypted", "customer_email_key_version",
            "customer_address_encrypted", "customer_address_key_version",
            "customer_gstin",
            "is_pii_erased", "pii_erased_at",
            "pdf_key",
            "updated_at",
        ])
        if old_pdf_key:
            try:
                from core.storage.resolve import delete_stored_media
                delete_stored_media(old_pdf_key)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "Could not delete PDF %s during PII erasure for invoice %s",
                    old_pdf_key, invoice.pk,
                )
        return invoice
