"""Invoice reader — the store & warehouse receiving agent (Gemini). Reads the
uploaded invoice photo/PDF/Excel into prefilled receive lines a person counts
against and confirms. Never the final writer."""

from __future__ import annotations

from typing import Any

from aiagents.gemini import extract

_SYSTEM = (
    "You read a supplier's tax invoice / packing list for an Indian apparel "
    "retailer (KDPS). Extract the line items so a warehouse/store operator can "
    "confirm a physical count. Quantities are integers. Reply with STRICT JSON "
    "only — no prose, no markdown fences."
)

_PROMPT = (
    "Extract this invoice as JSON with exactly this shape:\n"
    "{\n"
    '  "invoice_number": string|null,\n'
    '  "invoice_date": string|null,\n'
    '  "vendor_name": string|null,\n'
    '  "lines": [ {"style_code": string, "size": string|null, "color": string|null, '
    '"barcode": string|null, "quantity": integer, "mrp": number|null} ],\n'
    '  "missing": [string],\n'
    '  "confidence": number\n'
    "}\n"
    "One line per style+size. quantity is pieces. Do not invent data."
)


def read_invoice(content: bytes, content_type: str) -> dict[str, Any]:
    data = extract(content, content_type, _SYSTEM, _PROMPT)
    data.setdefault("lines", [])
    data.setdefault("missing", [])
    return data


_PT_PROMPT = (
    "Extract this supplier tax invoice as JSON with exactly this shape:\n"
    "{\n"
    '  "invoice_number": string|null,\n'
    '  "invoice_date": string|null,\n'
    '  "vendor_name": string|null,\n'
    '  "lines": [ {"style_code": string, "size": string|null, "color": string|null, '
    '"barcode": string|null, "quantity": integer, "mrp": number|null, '
    '"rate": number|null, "hsn": string|null, "gst_percent": number|null} ],\n'
    '  "freight": number|null,\n'
    '  "discount": number|null,\n'
    '  "gst_lines": [ {"rate_percent": number, "taxable_value": number, '
    '"tax_amount": number} ],\n'
    '  "missing": [string],\n'
    '  "confidence": number\n'
    "}\n"
    "One line per style+size. quantity is pieces. rate is the per-unit price the "
    "buyer pays BEFORE GST (the taxable unit rate, after any line discount) — never "
    "the MRP. mrp is the printed retail price if shown. hsn is the HSN/SAC code. "
    "gst_percent is the GST rate applied to that line (e.g. 5 or 18). freight and "
    "discount are invoice-level totals if shown. Do not invent data."
)


def read_invoice_for_pt(content: bytes, content_type: str) -> dict[str, Any]:
    """The richer read behind PT authoring (D2 non-brand path): the store/warehouse
    ``read_invoice`` shape plus per-line rate (what KDPS pays → BASIC / P RATE),
    HSN and GST, and invoice-level freight/discount. Same trust boundary: a draft
    a human reviews — never the final writer."""
    data = extract(content, content_type, _SYSTEM, _PT_PROMPT)
    data.setdefault("lines", [])
    data.setdefault("missing", [])
    return data
