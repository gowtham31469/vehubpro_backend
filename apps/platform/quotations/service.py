"""
QuotationService — lifecycle/revision/conversion logic for Quotation.

Design principles (mirrors InvoiceService)
-------------------------------------------
1. Atomicity: revision creation and job-card conversion each happen inside a single
   DB transaction — a failure at any step leaves no partial state.
2. Revisions never overwrite an approved quotation: create_revision() always inserts
   a brand-new Quotation row, flips `is_latest` atomically, and leaves the previous
   version fully intact for audit/history.
3. Only the latest version of an APPROVED quotation can be converted to a JobCard.
   Conversion copies the quotation's own line-item snapshot verbatim into new
   JobCardLineItem rows — it deliberately does NOT go through
   sync_job_card_line_items, which re-reads the *current* ServiceItem catalog and
   would silently diverge from what the customer actually approved.
4. The existing JobCard/Invoice modules are never modified by this service beyond
   creating a new JobCard row — direct (quotation-less) job card creation is
   completely unaffected.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.platform.quotations.models import Quotation, QuotationLineItem
from apps.platform.quotations.utils import refresh_quotation_totals


class QuotationError(Exception):
    """Base class for QuotationService errors."""


class InvalidQuotationStatus(QuotationError):
    """Raised when a status transition is attempted from an invalid current status."""


class QuotationNotLatestVersion(QuotationError):
    """Raised when an action requiring the latest version is attempted on a superseded one."""


class QuotationRevisionNotAllowed(QuotationError):
    """Raised when a revision is attempted from a status that doesn't support it."""


class QuotationAlreadyConverted(QuotationError):
    """Raised when attempting to convert a quotation that has already been converted."""


class QuotationService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    def apply_expiry_if_due(quotation: Quotation) -> Quotation:
        """
        Lazily flip SENT/APPROVED -> EXPIRED once `valid_until` has passed. There is
        no background task scheduler in this codebase (see jobcards/invoices, which
        also have no periodic jobs), so expiry is checked on read instead.
        """
        if (
            quotation.status in (Quotation.STATUS_SENT, Quotation.STATUS_APPROVED)
            and quotation.valid_until
            and quotation.valid_until < timezone.now().date()
        ):
            now = timezone.now()
            Quotation.objects.filter(pk=quotation.pk).update(status=Quotation.STATUS_EXPIRED, updated_at=now)
            quotation.status = Quotation.STATUS_EXPIRED
        return quotation

    @staticmethod
    @transaction.atomic
    def send(quotation: Quotation) -> Quotation:
        if quotation.status != Quotation.STATUS_DRAFT:
            raise InvalidQuotationStatus(
                f"Quotation '{quotation.quotation_number}' v{quotation.version} must be in "
                f"'draft' status to send (current: '{quotation.status}')."
            )
        if not quotation.line_items.exists():
            raise InvalidQuotationStatus("Cannot send a quotation with no line items.")
        now = timezone.now()
        Quotation.objects.filter(pk=quotation.pk).update(status=Quotation.STATUS_SENT, sent_at=now, updated_at=now)
        quotation.refresh_from_db()
        return quotation

    @staticmethod
    @transaction.atomic
    def approve(quotation: Quotation) -> Quotation:
        QuotationService.apply_expiry_if_due(quotation)
        if quotation.status != Quotation.STATUS_SENT:
            raise InvalidQuotationStatus(
                f"Quotation '{quotation.quotation_number}' v{quotation.version} must be in "
                f"'sent' status to approve (current: '{quotation.status}')."
            )
        now = timezone.now()
        Quotation.objects.filter(pk=quotation.pk).update(status=Quotation.STATUS_APPROVED, approved_at=now, updated_at=now)
        quotation.refresh_from_db()
        return quotation

    @staticmethod
    @transaction.atomic
    def reject(quotation: Quotation, *, reason: str = "") -> Quotation:
        QuotationService.apply_expiry_if_due(quotation)
        if quotation.status != Quotation.STATUS_SENT:
            raise InvalidQuotationStatus(
                f"Quotation '{quotation.quotation_number}' v{quotation.version} must be in "
                f"'sent' status to reject (current: '{quotation.status}')."
            )
        now = timezone.now()
        Quotation.objects.filter(pk=quotation.pk).update(
            status=Quotation.STATUS_REJECTED, rejected_at=now, rejection_reason=reason or "", updated_at=now
        )
        quotation.refresh_from_db()
        return quotation

    @staticmethod
    @transaction.atomic
    def cancel(quotation: Quotation, *, reason: str = "") -> Quotation:
        if quotation.status in (Quotation.STATUS_CANCELLED, Quotation.STATUS_CONVERTED):
            raise InvalidQuotationStatus(
                f"Quotation '{quotation.quotation_number}' v{quotation.version} is already "
                f"'{quotation.status}' and cannot be cancelled."
            )
        now = timezone.now()
        Quotation.objects.filter(pk=quotation.pk).update(
            status=Quotation.STATUS_CANCELLED, cancelled_at=now, cancellation_reason=reason or "", updated_at=now
        )
        quotation.refresh_from_db()
        return quotation

    @staticmethod
    @transaction.atomic
    def create_revision(quotation: Quotation, *, revision_reason: str, created_by) -> Quotation:
        """
        Create version N+1 of `quotation`'s family. `quotation` must be the current
        latest version, in SENT/APPROVED/REJECTED/EXPIRED status (DRAFT is already
        editable directly; CANCELLED/CONVERTED are dead ends). The new version starts
        as a DRAFT copy of every header field + a deep copy of every line item
        (fresh rows, not shared FKs), so editing it can never mutate the original.
        """
        QuotationService.apply_expiry_if_due(quotation)

        if not quotation.is_latest:
            raise QuotationNotLatestVersion("Only the latest version of a quotation can be revised.")
        if quotation.status not in (
            Quotation.STATUS_SENT,
            Quotation.STATUS_APPROVED,
            Quotation.STATUS_REJECTED,
            Quotation.STATUS_EXPIRED,
        ):
            raise QuotationRevisionNotAllowed(f"Cannot create a revision from a quotation in '{quotation.status}' status.")

        parent = quotation

        # Flip the parent's is_latest OFF first — the partial unique constraint
        # on (tenant, quotation_number) WHERE is_latest allows at most one such
        # row at any instant within the transaction, so the new version (also
        # is_latest=True) cannot be inserted while the parent still holds it.
        Quotation.objects.filter(pk=parent.pk).update(is_latest=False, updated_at=timezone.now())

        today = timezone.now().date()
        # The new version is dated today, so a validity date copied from an
        # already-expired parent (necessarily before today) would violate the
        # quotation_valid_until_after_date DB constraint — drop it instead and
        # let the advisor set a fresh one before sending.
        new_valid_until = parent.valid_until if parent.valid_until and parent.valid_until >= today else None

        new_version = Quotation.objects.create(
            tenant_id=parent.tenant_id,
            quotation_number=parent.quotation_number,
            version=parent.version + 1,
            parent_quotation=parent,
            is_latest=True,
            revision_reason=revision_reason,
            customer_id=parent.customer_id,
            vehicle_id=parent.vehicle_id,
            quotation_date=today,
            valid_until=new_valid_until,
            status=Quotation.STATUS_DRAFT,
            notes=parent.notes,
            terms_and_conditions=parent.terms_and_conditions,
            discount_amount=parent.discount_amount,
            created_by=created_by,
        )

        new_lines = [
            QuotationLineItem(
                quotation=new_version,
                sort_order=li.sort_order,
                service_item_id=li.service_item_id,
                service_type=li.service_type,
                description=li.description,
                detail_text=li.detail_text,
                quantity=li.quantity,
                unit_price=li.unit_price,
                discount_amount=li.discount_amount,
                line_total=li.line_total,
                gst_percentage=li.gst_percentage,
                cgst_amount=li.cgst_amount,
                sgst_amount=li.sgst_amount,
            )
            for li in parent.line_items.all()
        ]
        QuotationLineItem.objects.bulk_create(new_lines)
        refresh_quotation_totals(new_version)

        # Flip is_latest atomically: parent loses it, new version already has it.
        Quotation.objects.filter(pk=parent.pk).update(is_latest=False, updated_at=timezone.now())

        new_version.refresh_from_db()
        return new_version

    @staticmethod
    @transaction.atomic
    def convert_to_job_card(quotation: Quotation):
        """
        Convert an approved, latest-version quotation into a new JobCard. Both the
        quotation status flip and the JobCard creation happen in one transaction —
        either both succeed or both roll back. JobCard has no created_by field
        (see apps.platform.jobcards.models.JobCard) — the triggering user is
        captured separately via the audit log at the view layer.
        """
        from apps.platform.jobcards.models import JobCard, JobCardLineItem
        from apps.platform.jobcards.utils import allocate_next_jobcard_number, refresh_job_card_totals

        QuotationService.apply_expiry_if_due(quotation)

        if quotation.status == Quotation.STATUS_CONVERTED:
            raise QuotationAlreadyConverted(
                f"Quotation '{quotation.quotation_number}' v{quotation.version} has already been converted."
            )
        if not quotation.is_latest:
            raise QuotationNotLatestVersion("Only the latest version of a quotation can be converted to a job card.")
        if quotation.status != Quotation.STATUS_APPROVED:
            raise InvalidQuotationStatus(
                f"Quotation must be 'approved' to convert to a job card (current: '{quotation.status}')."
            )

        tenant_id = quotation.tenant_id
        job_card = JobCard.objects.create(
            tenant_id=tenant_id,
            jobcard_number=allocate_next_jobcard_number(tenant_id),
            customer_id=quotation.customer_id,
            vehicle_id=quotation.vehicle_id,
            quotation=quotation,
            discount_amount=quotation.discount_amount,
            notes=quotation.notes or "",
        )

        job_lines = [
            JobCardLineItem(
                job_card=job_card,
                sort_order=li.sort_order,
                service_item_id=li.service_item_id,
                service_type=li.service_type,
                description=li.description,
                detail_text=li.detail_text,
                quantity=li.quantity,
                unit_price=li.unit_price,
                discount_amount=li.discount_amount,
                line_total=li.line_total,
                gst_percentage=li.gst_percentage,
                cgst_amount=li.cgst_amount,
                sgst_amount=li.sgst_amount,
            )
            for li in quotation.line_items.all()
        ]
        JobCardLineItem.objects.bulk_create(job_lines)
        refresh_job_card_totals(job_card)

        now = timezone.now()
        Quotation.objects.filter(pk=quotation.pk).update(status=Quotation.STATUS_CONVERTED, converted_at=now, updated_at=now)

        job_card.refresh_from_db()
        return job_card
