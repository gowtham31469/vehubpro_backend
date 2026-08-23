"""
Shared helpers for rendering the "black-bar" PDF document template
(`jobcards/templates/jobcards/jobcard_preview.html`) — used for BOTH job cards and
invoices, parameterized by a handful of doc_type_label/doc_number_label/notes_label
context keys so the two document types stay pixel-identical by construction.
"""
from __future__ import annotations

from decimal import Decimal


def fmt_money(value) -> str:
    try:
        return f"{Decimal(str(value or 0)):,.2f}"
    except Exception:
        return "0.00"


def fmt_pct(value: Decimal) -> str:
    """Format a percentage without a misleading scientific-notation or trailing-zero tail."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def derive_pan_and_state_code(gstin: str | None) -> tuple[str, str]:
    """
    A GSTIN is: 2-digit state code + 10-char PAN + 1 entity code + 1 check
    digit + a default 'Z' (15 chars total) — so PAN and state code are just
    substrings of the GSTIN, not separately stored data.
    """
    gstin = (gstin or "").strip()
    if len(gstin) >= 12:
        return gstin[2:12], gstin[:2]
    return "", ""


# GST state/UT codes (first 2 digits of a GSTIN), per the CBIC jurisdiction list.
GST_STATE_NAMES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (Old)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}


def state_name_from_code(state_code: str | None) -> str:
    """State name for a 2-digit GST state code, or the code itself if unrecognized."""
    state_code = (state_code or "").strip()
    return GST_STATE_NAMES.get(state_code, state_code)


def fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return dt.strftime("%d.%m.%Y")


def split_lines_into_sections(lines, *, cgst_sgst_fn) -> dict:
    """
    `lines` — iterable of line-item objects with .service_type ('part'/'labour'),
    .description, .quantity, .unit_price, .line_total, .gst_percentage.
    `cgst_sgst_fn(line)` — returns (cgst: Decimal, sgst: Decimal) for one line — the
    caller decides how to derive this (read stored columns, or compute on the fly).

    Returns Parts/Labour line contexts, section totals, and per-section GST-rate
    labels (shown only when every line within that section shares the same GST%,
    independently per table — so one differently-taxed part doesn't hide the rate
    on an otherwise-uniform labour table or vice versa).
    """
    part_lines_ctx: list[dict] = []
    labour_lines_ctx: list[dict] = []
    parts_total = Decimal("0")
    labour_total = Decimal("0")
    parts_cgst = Decimal("0")
    parts_sgst = Decimal("0")
    labour_cgst = Decimal("0")
    labour_sgst = Decimal("0")
    part_rates: list[Decimal] = []
    labour_rates: list[Decimal] = []

    for line in lines:
        amount = Decimal(str(line.line_total or 0))
        rate = Decimal(str(line.gst_percentage or 0))
        cgst, sgst = cgst_sgst_fn(line)
        if line.service_type == "part":
            part_lines_ctx.append({
                "s_no": len(part_lines_ctx) + 1,
                "description": line.description,
                "quantity": Decimal(str(line.quantity)).normalize(),
                "unit_price": line.unit_price,
                "amount": amount,
            })
            parts_total += amount
            parts_cgst += cgst
            parts_sgst += sgst
            part_rates.append(rate)
        else:
            labour_lines_ctx.append({
                "s_no": len(labour_lines_ctx) + 1,
                "description": line.description,
                "amount": amount,
            })
            labour_total += amount
            labour_cgst += cgst
            labour_sgst += sgst
            labour_rates.append(rate)

    def _rate_label(rates):
        if rates and all(abs(r - rates[0]) < Decimal("0.01") for r in rates):
            return fmt_pct(rates[0] / 2)
        return None

    parts_gst = parts_cgst + parts_sgst
    labour_gst = labour_cgst + labour_sgst

    return {
        "part_lines": part_lines_ctx,
        "labour_lines": labour_lines_ctx,
        "parts_total": fmt_money(parts_total),
        "parts_cgst": fmt_money(parts_cgst),
        "parts_sgst": fmt_money(parts_sgst),
        "parts_total_with_gst": fmt_money(parts_total + parts_gst),
        "labour_total": fmt_money(labour_total),
        "labour_cgst": fmt_money(labour_cgst),
        "labour_sgst": fmt_money(labour_sgst),
        "labour_total_with_gst": fmt_money(labour_total + labour_gst),
        "parts_gst_rate_pct": _rate_label(part_rates),
        "labour_gst_rate_pct": _rate_label(labour_rates),
    }


def build_invoice_settings_pdf_context(invoice_settings, media_data_url_fn) -> dict:
    """Terms & conditions paragraphs + bank details + QR data URL, or safe empty defaults."""
    terms_paragraphs: list[str] = []
    bank_details = None
    qr_data_url = None

    if invoice_settings:
        if invoice_settings.terms_and_conditions and invoice_settings.show_terms_and_conditions:
            raw = invoice_settings.render_terms_and_conditions().replace("\r\n", "\n")
            terms_paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]

        if any([
            invoice_settings.account_holder_name,
            invoice_settings.account_number_encrypted,
            invoice_settings.ifsc_code,
            invoice_settings.bank_name,
            invoice_settings.upi_id,
        ]):
            account_number = ""
            try:
                if invoice_settings.account_number_encrypted:
                    account_number = invoice_settings.get_account_number()
            except Exception:
                account_number = ""
            bank_details = {
                "account_holder_name": invoice_settings.account_holder_name,
                "account_number": account_number,
                "account_type": invoice_settings.get_account_type_display() if invoice_settings.account_type else "",
                "ifsc_code": invoice_settings.ifsc_code,
                "bank_name": invoice_settings.bank_name,
                "branch_name": invoice_settings.branch_name,
                "upi_id": invoice_settings.upi_id,
            }
            qr_data_url = media_data_url_fn(invoice_settings.qr_code)

    return {"terms_paragraphs": terms_paragraphs, "bank_details": bank_details, "qr_data_url": qr_data_url}
