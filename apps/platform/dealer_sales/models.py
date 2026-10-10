from django.conf import settings
from django.db import models

from apps.common.utils.models import BaseModel, SoftArchiveModel


class VehicleAcquisition(BaseModel, SoftArchiveModel):
    """
    How a vehicle entered dealer stock — one record per InventoryVehicle.
    Owned vs. consignment field groups are both nullable here and validated
    against InventoryVehicle.inventory_type in the serializer (not a DB
    constraint), matching this codebase's existing validation convention.
    """

    METHOD_TRADE_IN = "trade_in"
    METHOD_AUCTION = "auction"
    METHOD_DIRECT_PURCHASE = "direct_purchase"
    METHOD_OTHER = "other"

    ACQUISITION_METHOD_CHOICES = [
        (METHOD_TRADE_IN, "Trade-In"),
        (METHOD_AUCTION, "Auction"),
        (METHOD_DIRECT_PURCHASE, "Direct Purchase"),
        (METHOD_OTHER, "Other"),
    ]

    COMMISSION_FIXED = "fixed"
    COMMISSION_PERCENTAGE = "percentage"
    COMMISSION_PRICE_DIFFERENCE = "price_difference"

    COMMISSION_TYPE_CHOICES = [
        (COMMISSION_FIXED, "Fixed Amount"),
        (COMMISSION_PERCENTAGE, "Percentage"),
        (COMMISSION_PRICE_DIFFERENCE, "Price Difference"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_acquisitions")
    vehicle = models.OneToOneField(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="acquisition"
    )
    acquisition_date = models.DateField()
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Owned-stock fields
    seller_customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles_sold_to_dealer",
    )
    seller_name = models.CharField(max_length=255, null=True, blank=True)
    seller_phone = models.CharField(max_length=20, null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    acquisition_method = models.CharField(
        max_length=20, choices=ACQUISITION_METHOD_CHOICES, null=True, blank=True
    )
    odometer_reading = models.PositiveIntegerField(null=True, blank=True)
    purchase_reference = models.CharField(max_length=100, null=True, blank=True)

    # Consignment fields
    owner_customer = models.ForeignKey(
        "customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="consigned_vehicles"
    )
    agreement_reference = models.CharField(max_length=100, null=True, blank=True)
    owner_expected_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    commission_type = models.CharField(max_length=20, choices=COMMISSION_TYPE_CHOICES, null=True, blank=True)
    commission_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    agreement_start_date = models.DateField(null=True, blank=True)
    agreement_end_date = models.DateField(null=True, blank=True)
    terms = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "dealer_vehicle_acquisitions"

    def __str__(self) -> str:
        return f"Acquisition for {self.vehicle_id}"


class VehicleOwnershipRecord(BaseModel):
    """Append-only ownership chain for a vehicle. Not soft-archived — history rows are immutable."""

    OWNER_PREVIOUS_OWNER = "previous_owner"
    OWNER_DEALER = "dealer"
    OWNER_CONSIGNOR = "consignor"
    OWNER_BUYER = "buyer"

    OWNER_TYPE_CHOICES = [
        (OWNER_PREVIOUS_OWNER, "Previous Owner"),
        (OWNER_DEALER, "Dealer"),
        (OWNER_CONSIGNOR, "Consignor"),
        (OWNER_BUYER, "Buyer"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_ownership_records")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="ownership_history"
    )
    owner_customer = models.ForeignKey(
        "customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Free text for owners not represented in the Customer table (e.g. "Previous Owner per RC").
    owner_name = models.CharField(max_length=255, null=True, blank=True)
    owner_type = models.CharField(max_length=20, choices=OWNER_TYPE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_ownership_records"
        ordering = ["start_date", "created_at"]

    def __str__(self) -> str:
        return f"{self.get_owner_type_display()} — {self.vehicle_id}"


class VehicleWorkExpense(BaseModel, SoftArchiveModel):
    """
    Reconditioning/work cost record for a vehicle. Deliberately has no FK to
    apps.platform.services or apps.platform.jobcards (the Garage module) —
    a portfolio user with zero Garage access must be able to log this, and
    the work may have been done by an external shop. Only records WHAT was
    done, WHO/WHERE, WHEN, and HOW MUCH it cost.
    """

    CATEGORY_CHOICES = [
        ("brake", "Brake"),
        ("engine", "Engine"),
        ("transmission", "Transmission"),
        ("suspension", "Suspension"),
        ("electrical", "Electrical"),
        ("ac", "AC"),
        ("tyre", "Tyre"),
        ("battery", "Battery"),
        ("painting", "Painting"),
        ("body_repair", "Body Repair"),
        ("denting", "Denting"),
        ("detailing", "Detailing"),
        ("oil_change", "Oil Change"),
        ("general_service", "General Service"),
        ("accessories", "Accessories"),
        ("interior", "Interior"),
        ("glass", "Glass"),
        ("cleaning", "Cleaning"),
        ("transport", "Transport"),
        ("insurance", "Insurance"),
        ("rto", "RTO"),
        ("documentation", "Documentation"),
        ("other", "Other"),
    ]

    PROVIDER_TYPE_CHOICES = [
        ("internal", "Internal"),
        ("external_garage", "External Garage"),
        ("paint_shop", "Paint Shop"),
        ("tyre_shop", "Tyre Shop"),
        ("body_shop", "Body Shop"),
        ("detailer", "Detailer"),
        ("electrician", "Electrician"),
        ("vendor", "Vendor"),
        ("other", "Other"),
    ]

    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_work_expenses")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="work_expenses"
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField()
    provider_name = models.CharField(max_length=255, null=True, blank=True)
    provider_type = models.CharField(max_length=20, choices=PROVIDER_TYPE_CHOICES, default="other")
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    receipt = models.CharField(max_length=500, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_COMPLETED, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_work_expenses"
        ordering = ["-expense_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "vehicle"]),
            models.Index(fields=["vehicle", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_category_display()} — {self.amount} ({self.vehicle_id})"


class VehiclePriceHistory(BaseModel):
    """Append-only log of every price change for a vehicle. Rows are system-generated, not user-POSTed."""

    PRICE_TYPE_CHOICES = [
        ("purchase_price", "Purchase Price"),
        ("owner_expected_price", "Owner Expected Price"),
        ("cost_price", "Cost Price"),
        ("asking_price", "Asking Price"),
        ("listing_price", "Listing Price"),
        ("quoted_price", "Quoted Price"),
        ("negotiated_price", "Negotiated Price"),
        ("final_sale_price", "Final Sale Price"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_price_history")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="price_history"
    )
    price_type = models.CharField(max_length=30, choices=PRICE_TYPE_CHOICES)
    old_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    new_value = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_price_history"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.get_price_type_display()}: {self.old_value} -> {self.new_value}"


class VehicleTimelineEvent(BaseModel):
    """
    Single authoritative chronological event feed for a vehicle's detail
    page. Append-only, mirrors apps.platform.portfolio.models.VisitRequestStatusEvent's
    pattern. Every mutating action in this app writes one row here instead of
    building a separate history/activity system per concept.
    """

    CATEGORY_CHOICES = [
        ("inventory", "Inventory"),
        ("ownership", "Ownership"),
        ("acquisition", "Acquisition"),
        ("inspection", "Inspection"),
        ("work_expense", "Work / Expense"),
        ("pricing", "Pricing"),
        ("listing", "Listing"),
        ("documents", "Documents"),
        ("status", "Status"),
        ("system", "System"),
        # Phase 2
        ("customer", "Customer"),
        ("quotation", "Quotation"),
        ("negotiation", "Negotiation"),
        ("reservation", "Reservation"),
        ("booking", "Booking"),
        ("sale", "Sale"),
        ("payment", "Payment"),
        ("settlement", "Settlement"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_timeline_events")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="timeline_events"
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_timeline_events"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["vehicle", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.vehicle_id})"


class VehicleDocument(BaseModel, SoftArchiveModel):
    """Generic document attachment for a vehicle — acquisition papers, work receipts, etc."""

    DOCUMENT_TYPE_CHOICES = [
        ("rc", "RC"),
        ("insurance", "Insurance"),
        ("puc", "PUC"),
        ("noc", "NOC"),
        ("purchase_document", "Purchase Document"),
        ("purchase_invoice", "Purchase Invoice"),
        ("consignment_agreement", "Consignment Agreement"),
        ("owner_authorization", "Owner Authorization"),
        ("kyc", "KYC"),
        ("work_receipt", "Vehicle Work Receipt"),
        ("other", "Other"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_documents")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    file = models.CharField(max_length=500)
    notes = models.TextField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_documents"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_document_type_display()} — {self.vehicle_id}"


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Quotation → Negotiation → Reservation → Booking → Sale →
# Delivery → Settlement. Same app, same conventions as Phase 1 above.
# ─────────────────────────────────────────────────────────────────────────


class DealerQuotationFySequence(BaseModel):
    """Per-tenant-per-FY counter for VehicleSaleQuotation numbering (mirrors
    apps.platform.quotations.models.QuotationFySequence)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="dealer_quotation_fy_sequences"
    )
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "dealer_quotation_fy_sequences"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_dealer_quotation_fy_seq_per_tenant"),
        ]


class VehicleSaleQuotation(BaseModel, SoftArchiveModel):
    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_NEGOTIATING = "negotiating"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CONVERTED = "converted"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SENT, "Sent"),
        (STATUS_NEGOTIATING, "Negotiating"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_CONVERTED, "Converted"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_sale_quotations")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="sale_quotations"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="vehicle_quotations")
    quotation_number = models.CharField(max_length=30, db_index=True)
    quoted_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dealer_vehicle_sale_quotations"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "quotation_number"], name="uniq_dealer_quotation_number_per_tenant"
            ),
        ]

    def __str__(self) -> str:
        return self.quotation_number


class VehicleNegotiation(BaseModel):
    """Append-only offer/counter-offer log for a VehicleSaleQuotation."""

    OFFERED_BY_CUSTOMER = "customer"
    OFFERED_BY_DEALER = "dealer"

    OFFERED_BY_CHOICES = [
        (OFFERED_BY_CUSTOMER, "Customer"),
        (OFFERED_BY_DEALER, "Dealer"),
    ]

    quotation = models.ForeignKey(
        VehicleSaleQuotation, on_delete=models.CASCADE, related_name="negotiations"
    )
    round_number = models.PositiveIntegerField()
    offered_by = models.CharField(max_length=10, choices=OFFERED_BY_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_negotiations"
        ordering = ["round_number"]

    def __str__(self) -> str:
        return f"Round {self.round_number} — {self.get_offered_by_display()}: {self.amount}"


class VehicleReservation(BaseModel, SoftArchiveModel):
    STATUS_ACTIVE = "active"
    STATUS_CONVERTED_TO_BOOKING = "converted_to_booking"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CONVERTED_TO_BOOKING, "Converted to Booking"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_reservations")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="reservations"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="vehicle_reservations")
    quotation = models.ForeignKey(
        VehicleSaleQuotation, on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations"
    )
    reservation_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_reservations"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Reservation — {self.vehicle_id} ({self.status})"


class VehicleBooking(BaseModel, SoftArchiveModel):
    STATUS_ACTIVE = "active"
    STATUS_CONVERTED_TO_SALE = "converted_to_sale"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CONVERTED_TO_SALE, "Converted to Sale"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_bookings")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="bookings"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="vehicle_bookings")
    reservation = models.ForeignKey(
        VehicleReservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )
    quotation = models.ForeignKey(
        VehicleSaleQuotation, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )
    booking_date = models.DateField()
    booking_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_bookings"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Booking — {self.vehicle_id} ({self.status})"


class VehicleSale(BaseModel, SoftArchiveModel):
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_sales")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.CASCADE, related_name="sales"
    )
    buyer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="vehicle_purchases")
    quotation = models.ForeignKey(
        VehicleSaleQuotation, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales"
    )
    booking = models.ForeignKey(
        VehicleBooking, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales"
    )
    sale_date = models.DateField()
    quoted_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    final_sale_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONFIRMED, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_sales"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Sale — {self.vehicle_id} ({self.status})"


class VehicleDelivery(BaseModel, SoftArchiveModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_deliveries")
    sale = models.OneToOneField(VehicleSale, on_delete=models.CASCADE, related_name="delivery")
    delivery_date = models.DateField()
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    handover_notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_deliveries"

    def __str__(self) -> str:
        return f"Delivery — {self.sale_id}"


class VehicleSettlement(BaseModel, SoftArchiveModel):
    """Consignment-only payout record — commission/owner-payable math is
    computed once at creation and stored, never recomputed live, so it stays
    historically explainable even if the underlying acquisition record
    changes later."""

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_settlements")
    sale = models.OneToOneField(VehicleSale, on_delete=models.CASCADE, related_name="settlement")
    commission_type = models.CharField(max_length=20)
    commission_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    dealer_expenses_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    owner_payable = models.DecimalField(max_digits=12, decimal_places=2)
    net_dealer_profit = models.DecimalField(max_digits=12, decimal_places=2)
    settlement_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    settlement_date = models.DateField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_settlements"

    def __str__(self) -> str:
        return f"Settlement — {self.sale_id} ({self.settlement_status})"


class DealerSaleInvoiceFySequence(BaseModel):
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="dealer_sale_invoice_fy_sequences"
    )
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "dealer_sale_invoice_fy_sequences"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_dealer_sale_invoice_fy_seq_per_tenant"),
        ]


class VehicleSaleInvoice(BaseModel):
    """Independent of apps.platform.invoices.Invoice, deliberately — that
    model's job_card FK is a required PROTECT and cannot be safely repurposed
    for a dealer sale without risking the Garage billing it already serves."""

    PAYMENT_STATUS_UNPAID = "unpaid"
    PAYMENT_STATUS_PARTIAL = "partial"
    PAYMENT_STATUS_PAID = "paid"

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_UNPAID, "Unpaid"),
        (PAYMENT_STATUS_PARTIAL, "Partial"),
        (PAYMENT_STATUS_PAID, "Paid"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_sale_invoices")
    sale = models.OneToOneField(VehicleSale, on_delete=models.CASCADE, related_name="invoice")
    invoice_number = models.CharField(max_length=30, db_index=True)

    buyer_name_snapshot = models.CharField(max_length=255)
    buyer_phone_snapshot = models.CharField(max_length=20, null=True, blank=True)
    buyer_email_snapshot = models.EmailField(null=True, blank=True)
    vehicle_label_snapshot = models.CharField(max_length=255)
    vehicle_registration_no_snapshot = models.CharField(max_length=50, null=True, blank=True)

    sale_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_status = models.CharField(
        max_length=10, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_UNPAID, db_index=True
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    # Storage key (LOCAL path or S3 key) for the last-generated PDF — mirrors
    # apps.platform.invoices.Invoice.pdf_key. Cleared implicitly on
    # regeneration (SaleInvoicePdfService purges the whole folder, not just
    # this tracked key, the same way the Garage invoice PDF service does).
    pdf_key = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "dealer_vehicle_sale_invoices"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "invoice_number"], name="uniq_dealer_sale_invoice_number_per_tenant"
            ),
        ]

    def __str__(self) -> str:
        return self.invoice_number


class VehicleSaleInvoicePayment(BaseModel):
    """Append-only payment ledger — mirrors apps.platform.invoices.InvoicePayment."""

    MODE_CASH = "cash"
    MODE_UPI = "upi"
    MODE_CARD = "card"
    MODE_BANK_TRANSFER = "bank_transfer"
    MODE_CHEQUE = "cheque"
    MODE_ADVANCE = "advance"

    PAYMENT_MODE_CHOICES = [
        (MODE_CASH, "Cash"),
        (MODE_UPI, "UPI"),
        (MODE_CARD, "Card"),
        (MODE_BANK_TRANSFER, "Bank Transfer"),
        (MODE_CHEQUE, "Cheque"),
        # System-generated row, not staff-entered — the reservation deposit
        # or booking amount already collected before the invoice existed,
        # auto-credited by generate_sale_invoice() rather than typed in.
        (MODE_ADVANCE, "Advance (Reservation/Booking)"),
    ]

    invoice = models.ForeignKey(VehicleSaleInvoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    payment_reference = models.CharField(max_length=100, null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "dealer_vehicle_sale_payments"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.amount} — {self.get_payment_mode_display()}"
