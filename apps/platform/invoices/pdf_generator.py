"""
Invoice PDF generation using Playwright.

Renders the invoice preview HTML directly to PDF using headless browser.
This ensures the PDF matches the web preview pixel-perfectly.
"""
import asyncio
import io
import logging
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


async def generate_invoice_pdf_async(html_content: str) -> bytes:
    """
    Generate PDF from HTML using Playwright headless browser.

    This renders the exact same HTML/CSS as the web preview, ensuring
    pixel-perfect consistency between preview and PDF.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed")
        raise ImportError("playwright is required for PDF generation")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            # Set viewport to A4 proportions
            await page.set_viewport_size({"width": 1024, "height": 1448})

            # Load the HTML content
            await page.set_content(html_content, wait_until="networkidle")

            # Generate PDF with A4 settings
            pdf_bytes = await page.pdf(
                format="A4",
                margin={
                    "top": "20mm",
                    "right": "22mm",
                    "bottom": "20mm",
                    "left": "22mm",
                },
                print_background=True,
            )

            return pdf_bytes
        finally:
            await browser.close()


def generate_invoice_pdf(html_content: str) -> bytes:
    """
    Synchronous wrapper for async PDF generation.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(generate_invoice_pdf_async(html_content))
    finally:
        loop.close()


def render_invoice_preview_html(invoice) -> str:
    """
    Render invoice as standalone HTML (matching the web preview exactly).

    Returns the complete HTML document that can be converted to PDF.
    """
    # Build the same context as the preview component
    from apps.platform.invoices.serializers import InvoiceDetailSerializer

    invoice_data = InvoiceDetailSerializer(invoice).data

    # Debug: log what fields are in the serialized data
    logger.debug("Invoice serialized data keys: %s", list(invoice_data.keys()))
    logger.debug("tenant_address_snapshot in data: %s", 'tenant_address_snapshot' in invoice_data)
    if 'tenant_address_snapshot' in invoice_data:
        logger.debug("tenant_address_snapshot value: %s", invoice_data.get('tenant_address_snapshot'))

    # Calculate derived values (same as preview)
    is_paid = invoice.payment_status == 'paid'
    is_partial = invoice.payment_status == 'partial'
    balance = max(0, float(invoice.total_amount or 0) - float(invoice.amount_paid or 0))

    total_gst = (
        float(invoice.cgst_amount or 0) +
        float(invoice.sgst_amount or 0) +
        float(invoice.igst_amount or 0)
    )

    # Get GST rates from line items
    gst_rates = set()
    for line in invoice.line_items.all():
        rate = float(line.gst_percentage or 0)
        if rate:
            gst_rates.add(rate)

    if len(gst_rates) == 1:
        gst_label = f"{list(gst_rates)[0]:.0f}%"
    else:
        gst_label = "GST"

    # Get tenant branding
    try:
        from apps.platform.tenants.models import TenantBranding
        branding = TenantBranding.objects.filter(tenant_id=invoice.tenant_id).first()
        accent_color = branding.primary_color if branding and branding.primary_color else "#1d4ed8"
    except Exception:
        accent_color = "#1d4ed8"

    context = {
        "invoice": invoice_data,
        "is_paid": is_paid,
        "is_partial": is_partial,
        "balance": balance,
        "total_gst": total_gst,
        "gst_label": gst_label,
        "accent_color": accent_color,
    }

    # Render the preview HTML template
    html = render_to_string("invoices/invoice_preview.html", context)

    # Debug: save HTML to temp file for inspection
    import tempfile
    temp_path = tempfile.gettempdir()
    debug_file = f"{temp_path}/invoice_{invoice.id}_debug.html"
    try:
        with open(debug_file, 'w') as f:
            f.write(html)
        logger.info("Debug HTML saved to: %s", debug_file)
    except Exception as e:
        logger.warning("Could not save debug HTML: %s", e)

    return html
