"""Invoice reader — the store & warehouse receiving agent (Gemini). Reads the
uploaded invoice photo/PDF/Excel into prefilled receive lines a person counts
against and confirms. Never the final writer."""

from __future__ import annotations

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


def read_invoice(content: bytes, content_type: str) -> dict:
    data = extract(content, content_type, _SYSTEM, _PROMPT)
    data.setdefault("lines", [])
    data.setdefault("missing", [])
    return data
