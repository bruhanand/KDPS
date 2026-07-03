"""Authoring a PT from a GRN — the non-brand / direct-receipt path (D2 Q4/Q7/Q8).

A non-brand PT is not *mapped* from a brand file — it is *authored* from the
GRN's counted lines, with the invoice photo (read by AI) as a prefill. The output
is the same ``PtFile``/``PtRow`` shape the brand path produces, so everything
downstream — the editor grid with Master-vocabulary type-and-select, blanks
tracking, send → Patna → ``post_pt_inward`` (P-RATE valuation, cost ≤ MRP block,
SKU/Cohort registration), reverse, export — is reused unchanged.

Two trust levels (Rule 8):
  * GRN facts a human counted (style, size, colour, barcode, qty) land with
    provenance ``direct`` — the count always wins;
  * invoice values the AI read (rate, MRP, HSN, GST) land with provenance
    ``inferred`` and only ever fill *blank* cells — reviewable, never final.
"""

from __future__ import annotations

from typing import Any

from ptmapper.engine import Resolver, _quantity_out, norm, raw_str
from ptmapper.models import PtFile, PtRow
from ptmapper.profiles import CONTROLLED, KDPS_COLUMNS

#: Q29 — a GRN line with no size is Free Size, never blank (a real Master value).
FREE_SIZE = "FREE SIZE"


def _blank_row() -> dict[str, Any]:
    return dict.fromkeys(KDPS_COLUMNS, "")


def _resolve_or_blank(value: str, resolve) -> tuple[str, str]:
    """Resolve a GRN free-text value through the lookup tables → ``(value, source)``;
    an unknown value stays blank (the operator fills it in the editor — authoring
    misses are NOT pushed to the review queue, the human is already in the loop)."""
    if not value:
        return "", ""
    resolved, src = resolve(value)
    return (resolved, src) if resolved else ("", "")


def build_pt_from_grn(grn: Any, user: Any) -> PtFile:
    """Create a DRAFT ``PtFile(source=invoice, grn=…)`` with one row per sellable
    GRN line. Damaged-only lines (received 0) never become stock."""
    resolver = Resolver()  # misses intentionally not synced to the review queue
    vendor_name = raw_str(grn.vendor.name if grn.vendor else grn.vendor_name_raw)
    brand_v, brand_s = _resolve_or_blank(vendor_name, resolver.brand)

    rows: list[dict[str, Any]] = []
    skipped_damaged_only = 0
    for line in grn.lines.all():
        if line.received_qty <= 0:
            skipped_damaged_only += 1
            continue
        color_v, color_s = _resolve_or_blank(line.color, lambda v: resolver.color(v, brand=brand_v))
        if raw_str(line.size):
            size_v, size_s = _resolve_or_blank(line.size, lambda v: resolver.size(v, brand=brand_v))
        else:
            size_v, size_s = FREE_SIZE, "derived"  # Q29 — sizeless goods are Free Size

        data = _blank_row()
        data.update(
            {
                "BRAND": brand_v,
                "COLOR": color_v,
                "SIZE": size_v,
                "BARCODE": raw_str(line.barcode),
                "DESIGN": raw_str(line.style_code),
                "QTY": _quantity_out(float(line.received_qty)),
                "NAG": _quantity_out(float(line.received_qty)),
            }
        )
        provenance = {
            "BRAND": brand_s,
            "COLOR": color_s,
            "SIZE": size_s,
            "BARCODE": "direct" if data["BARCODE"] else "",
            "DESIGN": "direct" if data["DESIGN"] else "",
            "QTY": "direct",
            "NAG": "derived",
        }
        raw = {
            "BRAND": vendor_name[:300],
            "COLOR": raw_str(line.color)[:300],
            "SIZE": raw_str(line.size)[:300],
        }
        rows.append(
            {
                "data": data,
                "blanks": [c for c in CONTROLLED if not data[c]],
                "provenance": {k: v for k, v in provenance.items() if v},
                "raw": {k: v for k, v in raw.items() if v},
            }
        )

    filename = (
        grn.invoice_file.filename if grn.invoice_file else f"{grn.doc_number} (direct receipt)"
    )
    pt = PtFile.objects.create(
        source=PtFile.Source.INVOICE,
        grn=grn,
        stored_file=grn.invoice_file,
        original_filename=filename[:255],
        brand_guess=brand_v or norm(vendor_name),
        profile_code="INVOICE",
        profile_name="Authored from GRN (non-brand)",
        archetype="INV",
        meta={
            "grn_number": grn.doc_number,
            "invoice_number": grn.invoice_number,
            **({"skipped_damaged_only": skipped_damaged_only} if skipped_damaged_only else {}),
        },
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    PtRow.objects.bulk_create(
        [
            PtRow(
                pt_file=pt,
                line_no=i,
                data=r["data"],
                blanks=r["blanks"],
                provenance=r["provenance"],
                raw=r["raw"],
            )
            for i, r in enumerate(rows, start=1)
        ]
    )
    pt.row_count = len(rows)
    pt.blank_cell_count = sum(len(r["blanks"]) for r in rows)
    pt.status = (
        PtFile.Status.READY if (rows and pt.blank_cell_count == 0) else PtFile.Status.NEEDS_REVIEW
    )
    pt.save(update_fields=["row_count", "blank_cell_count", "status", "updated_at"])
    return pt


# ------------------------------------------------------------- invoice enrichment
def _gst_out(value: Any) -> Any:
    """A GST percent cell as the engine writes it: whole floats collapse to int
    (5.0 → 5) so it compares clean against the Master '5'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    return int(f) if f == int(f) else f


def _money_out(value: Any) -> Any:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return ""


#: Extract-line key → the KDPS money/identity cells it may fill (blank cells only).
_EXTRACT_CELLS: list[tuple[str, str, Any]] = [
    ("rate", "P RATE", _money_out),
    ("rate", "BASIC", _money_out),  # Q36: P RATE = the ex-GST payable = rate, directly
    ("mrp", "MRP", _money_out),
    ("hsn", "HSN", lambda v: raw_str(v)[:24]),
    ("gst_percent", "INPUT TAX", _gst_out),
    ("gst_percent", "OUTPUT TAX", _gst_out),
]


def _extract_index(extract: dict) -> tuple[dict[tuple[str, str], dict], dict[str, list[dict]]]:
    by_style_size: dict[tuple[str, str], dict] = {}
    by_style: dict[str, list[dict]] = {}
    for line in extract.get("lines") or []:
        style = norm(line.get("style_code"))
        if not style:
            continue
        by_style_size.setdefault((style, norm(line.get("size"))), line)
        by_style.setdefault(style, []).append(line)
    return by_style_size, by_style


def _match_line(row: PtRow, by_style_size: dict, by_style: dict) -> dict | None:
    """The invoice line behind a GRN-seeded row: exact (style, size) first — the raw
    GRN size, since the row's SIZE may already be normalised — then style alone when
    the invoice carries it exactly once (no guessing across sizes)."""
    style = norm(row.data.get("DESIGN"))
    if not style:
        return None
    for size in (norm((row.raw or {}).get("SIZE")), norm(row.data.get("SIZE"))):
        hit = by_style_size.get((style, size))
        if hit:
            return hit
    candidates = by_style.get(style, [])
    return candidates[0] if len(candidates) == 1 else None


def apply_invoice_extract(pt: PtFile, extract: dict) -> int:
    """Merge the AI invoice read onto the authored rows: fill *blank* money/identity
    cells with provenance ``inferred`` (Rule 8 — reviewable, never final). QTY is
    never touched: the GRN's counted quantity always wins over the invoice."""
    by_style_size, by_style = _extract_index(extract)
    touched: list[PtRow] = []
    filled = 0
    for row in pt.rows.all():
        line = _match_line(row, by_style_size, by_style)
        if not line:
            continue
        data = {**row.data}
        prov = {**(row.provenance or {})}
        changed = False
        for src_key, col, out in _EXTRACT_CELLS:
            if str(data.get(col) or "").strip():
                continue  # never overwrite — the count/human/GRN value wins
            value = out(line.get(src_key))
            if value == "" or value is None:
                continue
            data[col] = value
            prov[col] = "inferred"
            changed = True
            filled += 1
        if changed:
            row.data, row.provenance = data, prov
            touched.append(row)
    if touched:
        PtRow.objects.bulk_update(touched, ["data", "provenance"])
    return filled


def enrich_from_invoice(pt: PtFile, grn: Any) -> None:
    """Best-effort AI prefill from the GRN's stored invoice. Failure never blocks
    authoring — the error is recorded on the file and the operator types instead."""
    if not grn.invoice_file:
        return
    from inbound.agents import read_invoice_for_pt

    try:
        extract = read_invoice_for_pt(
            bytes(grn.invoice_file.content), grn.invoice_file.content_type
        )
    except Exception as exc:  # noqa: BLE001 — the prefill is optional by design
        pt.meta = {**pt.meta, "invoice_extract_error": str(exc)[:300]}
        pt.save(update_fields=["meta", "updated_at"])
        return
    filled = apply_invoice_extract(pt, extract)
    pt.meta = {
        **pt.meta,
        "invoice_extract": {
            "invoice_number": extract.get("invoice_number"),
            "invoice_date": extract.get("invoice_date"),
            "vendor_name": extract.get("vendor_name"),
            "freight": extract.get("freight"),
            "discount": extract.get("discount"),
            "confidence": extract.get("confidence"),
            "line_count": len(extract.get("lines") or []),
            "cells_filled": filled,
        },
    }
    pt.save(update_fields=["meta", "updated_at"])
