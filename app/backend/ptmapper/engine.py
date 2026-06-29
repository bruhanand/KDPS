"""The deterministic PT mapping engine.

No AI. A brand file is read, its header located, columns mapped per profile,
values normalised through DB lookup tables, derived fields computed, and anything
unresolved is pushed to the review queue (never guessed). Re-running after a
lookup is added needs zero code change.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

import openpyxl

from ptmapper.models import ControlledValue, ItemTaxonomy, Lookup, TaxonomyRule
from ptmapper.profiles import (
    ALIASES,
    CONTROLLED,
    FILENAME_HINTS,
    GENERIC_PROFILE,
    HEADER_KEYWORDS,
    PROFILES,
)

MAX_ROWS = 8000


@dataclass(frozen=True)
class BaseMappedFields:
    barcode: str
    design: str
    qty: float | None
    mrp: float | None
    desc: str
    raw_brand: str


@dataclass(frozen=True)
class PriceFields:
    prate: float | None
    basic: float | None
    input_tax: float | None


@dataclass(frozen=True)
class ResolvedFields:
    brand: str | None
    color: str | None
    size: str | None
    season: str | None
    taxonomy: dict


class UnsupportedFormat(Exception):
    pass


# ----------------------------------------------------------------------------- helpers
def norm(v: Any) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).strip()).upper()


def raw_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def money(v: Any) -> float | None:
    n = num(v)
    return round(n, 2) if n is not None else None


def clean_code(v: Any) -> str:
    """Stringify a barcode/HSN without a spurious trailing .0 from float cells."""
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s


_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y%m%d", "%m/%d/%Y",
]


def parse_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    # Excel serial date (common in .xlsb exports where dates arrive as numbers).
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:
        try:
            return (datetime(1899, 12, 30) + timedelta(days=int(v))).date()
        except Exception:  # noqa: BLE001
            return None
    s = raw_str(v)
    if not s:
        return None
    s = s.split(".")[0] if s.isdigit() and len(s) > 8 else s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def season_label(d: date) -> str:
    prefix = "SPRING SUMMER" if d.month <= 6 else "AUTUMN WINTER"
    return f"{prefix}({d.strftime('%b')}-{d.strftime('%y')})"


# ----------------------------------------------------------------------------- reading
def _read_xlsx(content: bytes) -> list[tuple[str, list[list]]]:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    out: list[tuple[str, list[list]]] = []
    for ws in wb.worksheets:
        rows: list[list] = []
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            rows.append(list(r))
            if i >= MAX_ROWS:
                break
        out.append((ws.title, rows))
    wb.close()
    return out


def _read_csv(content: bytes) -> list[tuple[str, list[list]]]:
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnsupportedFormat("Could not decode the CSV text.")
    rows = list(csv.reader(io.StringIO(text)))[:MAX_ROWS + 1]
    return [("csv", rows)]


def _read_xls(content: bytes) -> list[tuple[str, list[list]]]:
    """Legacy OLE2 .xls via xlrd; Excel serial dates → datetime."""
    import xlrd

    book = xlrd.open_workbook(file_contents=content)
    out: list[tuple[str, list[list]]] = []
    for sh in book.sheets():
        rows: list[list] = []
        for i in range(min(sh.nrows, MAX_ROWS + 1)):
            row: list = []
            for j in range(sh.ncols):
                cell = sh.cell(i, j)
                v = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        v = xlrd.xldate_as_datetime(cell.value, book.datemode)
                    except Exception:  # noqa: BLE001
                        pass
                row.append(v)
            rows.append(row)
        out.append((sh.name, rows))
    return out


def _read_xlsb(content: bytes) -> list[tuple[str, list[list]]]:
    """Binary .xlsb (e.g. Madura SAP export) via pyxlsb."""
    from pyxlsb import open_workbook as open_xlsb

    out: list[tuple[str, list[list]]] = []
    with open_xlsb(io.BytesIO(content)) as wb:
        for name in wb.sheets:
            rows: list[list] = []
            with wb.get_sheet(name) as sheet:
                for i, row in enumerate(sheet.rows()):
                    rows.append([c.v for c in row])
                    if i >= MAX_ROWS:
                        break
            out.append((name, rows))
    return out


def read_sheets(content: bytes, filename: str, content_type: str) -> list[tuple[str, list[list]]]:
    name = (filename or "").lower()
    is_zip = content[:4] == b"PK\x03\x04"  # xlsx / xlsb are both ZIP containers
    is_ole = content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy OLE2 .xls

    # .xlsb is a ZIP too, so it must be matched by extension before the ZIP sniff.
    if name.endswith(".xlsb"):
        return _read_xlsb(content)
    # Real container wins over a (possibly wrong) extension — covers .xls/.csv that
    # are actually .xlsx, and .csv/.xls that are actually OLE2 .xls.
    if is_zip:
        return _read_xlsx(content)
    if is_ole:
        return _read_xls(content)
    if name.endswith(".xlsx") or "spreadsheetml" in (content_type or ""):
        return _read_xlsx(content)
    if name.endswith(".xls"):
        return _read_xls(content)
    if name.endswith(".csv") or "csv" in (content_type or ""):
        return _read_csv(content)
    raise UnsupportedFormat(
        "Unsupported file type. Upload a .xlsx, .xls, .xlsb or .csv brand PT file."
    )


# ----------------------------------------------------------------------------- detection
def score_header(row: list) -> float:
    s = 0.0
    for c in row:
        cv = raw_str(c).lower()
        if not cv:
            continue
        if cv in HEADER_KEYWORDS:
            s += 1
        elif len(cv) < 40 and any(k in cv for k in HEADER_KEYWORDS):
            s += 0.5
    return s


def detect_header(rows: list[list]) -> int:
    best_i, best = 0, -1.0
    for i in range(min(16, len(rows))):
        sc = score_header(rows[i])
        if sc > best:
            best, best_i = sc, i
    return best_i


def _has_data(rows: list[list]) -> bool:
    return any(any(raw_str(c) for c in r) for r in rows[:30])


def choose_sheet(sheets: list[tuple[str, list[list]]]) -> tuple[str, list[list]]:
    # Prefer a sheet whose name matches a profile's sheet_contains token.
    for p in PROFILES:
        sc = p["match"].get("sheet_contains")
        if sc:
            for name, rows in sheets:
                if sc in name.upper() and _has_data(rows):
                    return name, rows
    # Else the non-empty sheet with the best-scoring header row.
    best = None
    best_score = -1.0
    for name, rows in sheets:
        if not _has_data(rows):
            continue
        hi = detect_header(rows)
        sc = score_header(rows[hi]) + min(len(rows), 100) * 0.001
        if sc > best_score:
            best_score, best = sc, (name, rows)
    return best or sheets[0]


def profile_by_code(code: str) -> dict:
    for p in PROFILES:
        if p["code"] == code:
            return p
    return GENERIC_PROFILE


def identify_profile(filename: str, header_set: set[str], sheet_name: str) -> dict:
    up = (filename or "").upper()
    for kw, code in FILENAME_HINTS.items():
        if kw in up:
            return profile_by_code(code)
    for p in PROFILES:
        m = p["match"]
        if not m:
            continue
        if m.get("sheet_contains") and m["sheet_contains"] not in (sheet_name or "").upper():
            continue
        if m.get("header_has") and not all(h in header_set for h in m["header_has"]):
            continue
        return p
    return GENERIC_PROFILE


def build_records(rows: list[list], header_idx: int) -> list[dict[str, Any]]:
    headers = [norm(c) for c in rows[header_idx]]
    records: list[dict[str, Any]] = []
    blanks_in_a_row = 0
    for r in rows[header_idx + 1:]:
        if not any(raw_str(c) for c in r):
            blanks_in_a_row += 1
            if blanks_in_a_row >= 3:
                break
            continue
        blanks_in_a_row = 0
        first = raw_str(r[0]).lower() if r else ""
        if first.startswith("total") or first.startswith("grand total"):
            break
        rec: dict[str, Any] = {}
        for j, h in enumerate(headers):
            if h and j < len(r):
                rec.setdefault(h, r[j])
        records.append(rec)
    return records


# ----------------------------------------------------------------------------- resolver
class Resolver:
    """DB-backed value normaliser; records every miss for the review queue."""

    def __init__(self) -> None:
        self.controlled: dict[str, set[str]] = {}
        for cv in ControlledValue.objects.all():
            self.controlled.setdefault(cv.dimension, set()).add(cv.value)
        self.lookups: dict[str, dict[str, str]] = {}
        for lk in Lookup.objects.all():
            self.lookups.setdefault(lk.dimension, {})[lk.source_key] = lk.target_value
        self.item_taxonomy = {
            it.item: (it.sub_category, it.type) for it in ItemTaxonomy.objects.all()
        }
        self.rules = list(TaxonomyRule.objects.all())  # ordered -priority
        self.misses: dict[tuple[str, str], dict] = {}

    def _miss(self, dimension: str, raw: str, ctx: dict | None = None) -> None:
        raw = raw.strip()[:300]
        if not raw:
            return
        rec = self.misses.setdefault(dimension + "|" + raw, {"dimension": dimension, "raw": raw, "occurrences": 0, "samples": []})
        rec["occurrences"] += 1
        if ctx and len(rec["samples"]) < 5:
            sample = ctx.get("desc") or ctx.get("brand") or ""
            if sample and sample not in rec["samples"]:
                rec["samples"].append(sample[:120])

    def _single(self, dimension: str, raw_value: str, ctx: dict | None = None) -> str | None:
        key = norm(raw_value)
        if not key:
            return None
        hit = self.lookups.get(dimension, {}).get(key)
        if hit:
            return hit
        self._miss(dimension, raw_value, ctx)
        return None

    def brand(self, raw_value: str, ctx=None):
        return self._single("brand", raw_value, ctx)

    def color(self, raw_value: str, ctx=None):
        return self._single("color", raw_value, ctx)

    def size(self, raw_value: Any, ctx=None):
        return self._single("size", clean_code(raw_value), ctx)

    def gender(self, raw_value: str):
        key = norm(raw_value)
        if not key:
            return ""
        return self.lookups.get("gender", {}).get(key, "")

    def season_from_date(self, d: date):
        label = season_label(d)
        if label in self.controlled.get("season", set()):
            return label
        return None

    def season_from_code(self, code: str, ctx=None):
        key = norm(code)
        if not key:
            return None
        hit = self.lookups.get("season", {}).get(key)
        if hit:
            return hit
        self._miss("season", code, ctx)
        return None

    def taxonomy(self, desc: str, ctx=None) -> dict:
        up = " " + norm(desc) + " "
        for rule in self.rules:
            if norm(rule.pattern) in up:
                return {
                    "gender": rule.gender, "sub_category": rule.sub_category,
                    "type": rule.type, "item": rule.item, "fit": rule.fit,
                }
        if desc.strip():
            self._miss("taxonomy", desc, ctx or {"desc": desc})
        return {}


# ----------------------------------------------------------------------------- mapping
def _pick(rec: dict, role: str, profile: dict) -> Any:
    override = profile.get("overrides", {}).get(role)
    if override:
        if isinstance(override, list):
            return [rec.get(norm(c)) for c in override]
        return rec.get(norm(override))
    for alias in ALIASES.get(role, []):
        if alias in rec and raw_str(rec[alias]):
            return rec[alias]
    return None


def _build_desc(rec: dict, profile: dict) -> str:
    cols = profile.get("overrides", {}).get("DESC_SRC") or ALIASES["DESC_SRC"]
    parts = []
    for c in cols:
        v = raw_str(rec.get(norm(c)))
        if v:
            parts.append(v)
    return " ".join(parts)


def _getter(rec: dict, profile: dict) -> Callable[[str], Any]:
    return lambda role: _pick(rec, role, profile)


def _extract_base_fields(
    rec: dict,
    profile: dict,
    g: Callable[[str], Any],
    brand_default: str,
) -> BaseMappedFields:
    return BaseMappedFields(
        barcode=clean_code(g("BARCODE")),
        design=raw_str(g("DESIGN")),
        qty=num(g("QTY")),
        mrp=money(g("MRP")),
        desc=_build_desc(rec, profile),
        raw_brand=raw_str(g("BRAND_SRC")) or brand_default,
    )


def _has_mappable_payload(base: BaseMappedFields) -> bool:
    return bool((base.barcode or base.design) and (base.qty is not None or base.mrp is not None))


def _map_prices(rec: dict, profile: dict, g, qty: float | None) -> tuple:
    """(P RATE, BASIC, INPUT TAX). BASIC may be derived per-unit from taxable amount."""
    prate = money(g("PRATE_SRC"))
    if profile.get("flags", {}).get("basic_from_taxable_per_unit"):
        tax_amt = num(rec.get("TAXABLE_AMOUNT"))
        basic = round(tax_amt / qty, 2) if (tax_amt and qty) else money(g("BASIC_SRC"))
    else:
        basic = money(g("BASIC_SRC"))
    return prate, basic, num(g("TAX_SRC"))


def _price_fields(rec: dict, profile: dict, g, qty: float | None) -> PriceFields:
    prate, basic, input_tax = _map_prices(rec, profile, g, qty)
    return PriceFields(prate=prate, basic=basic, input_tax=input_tax)


def _map_season(resolver: "Resolver", g, ctx: dict) -> str | None:
    """SEASON from the invoice date if available, else from a season code."""
    d = parse_date(g("DATE_SRC"))
    season = resolver.season_from_date(d) if d else None
    if not season:
        season = resolver.season_from_code(raw_str(g("SEASON_SRC")), ctx)
    return season


def _map_taxonomy(resolver: "Resolver", desc: str, g, ctx: dict) -> dict:
    """The 5-axis merchandising grid (+ ITEM-suggested sub/type) for one row."""
    tax = resolver.taxonomy(desc, ctx)
    gender = resolver.gender(raw_str(g("GENDER_SRC"))) or tax.get("gender", "")
    item, fit = tax.get("item", ""), tax.get("fit", "")
    sub, typ = tax.get("sub_category", ""), tax.get("type", "")
    sug_sub = sug_type = ""
    if item and item in resolver.item_taxonomy:
        sug_sub, sug_type = resolver.item_taxonomy[item]
        sub = sub or sug_sub
        typ = typ or sug_type
    return {
        "gender": gender, "item": item, "fit": fit, "sub": sub, "typ": typ,
        "sug_sub": sug_sub, "sug_type": sug_type,
    }


def _resolve_fields(resolver: "Resolver", g: Callable[[str], Any], base: BaseMappedFields) -> ResolvedFields:
    ctx = {"brand": base.raw_brand, "desc": base.desc}
    return ResolvedFields(
        brand=resolver.brand(base.raw_brand, ctx),
        color=resolver.color(raw_str(g("COLOR_SRC")), ctx),
        size=resolver.size(g("SIZE_SRC"), ctx),
        season=_map_season(resolver, g, ctx),
        taxonomy=_map_taxonomy(resolver, base.desc, g, ctx),
    )


def _margin(mrp: float | None, prate: float | None) -> float | str:
    return round((mrp - prate) / mrp * 100, 2) if (mrp and prate and mrp > 0) else ""


def _quantity_out(qty: float | None) -> int | str:
    return int(qty) if qty else ""


def _build_kdps_row(
    base: BaseMappedFields,
    prices: PriceFields,
    resolved: ResolvedFields,
    g: Callable[[str], Any],
) -> dict:
    tx = resolved.taxonomy
    input_tax = prices.input_tax if prices.input_tax is not None else ""
    return {
        "SEASON": resolved.season or "", "BRAND": resolved.brand or "", "COLOR": resolved.color or "",
        "GENDER": tx["gender"] or "", "SUB CATEGORY": tx["sub"] or "", "TYPE": tx["typ"] or "",
        "ITEM": tx["item"] or "", "FIT": tx["fit"] or "", "SIZE": resolved.size or "",
        "BARCODE": base.barcode, "DESIGN": base.design, "HSN": clean_code(g("HSN")),
        "QTY": _quantity_out(base.qty), "MRP": base.mrp if base.mrp is not None else "",
        "BASIC": prices.basic if prices.basic is not None else "",
        "P RATE": prices.prate if prices.prate is not None else "",
        "INPUT TAX": input_tax, "OUTPUT TAX": input_tax,
        "NAG": _quantity_out(base.qty), "MARGIN": _margin(base.mrp, prices.prate),
        "SUGGESTED SUB CATEGORY": tx["sug_sub"], "SUGGESTED TYPE": tx["sug_type"],
    }


def _blank_controlled_columns(row: dict) -> list:
    return [column for column in CONTROLLED if not row[column]]


def map_record(rec: dict, profile: dict, resolver: Resolver, brand_default: str) -> tuple[dict, list] | None:
    g = _getter(rec, profile)
    base = _extract_base_fields(rec, profile, g, brand_default)
    if not _has_mappable_payload(base):
        return None
    prices = _price_fields(rec, profile, g, base.qty)
    resolved = _resolve_fields(resolver, g, base)
    row = _build_kdps_row(base, prices, resolved, g)
    return row, _blank_controlled_columns(row)


def run_mapping(content: bytes, filename: str, content_type: str) -> dict:
    """Map a brand file into KDPS rows + review misses. Pure read (no DB writes)."""
    sheets = read_sheets(content, filename, content_type)
    sheet_name, rows = choose_sheet(sheets)
    truncated = len(rows) > MAX_ROWS
    header_idx = detect_header(rows)
    headers = [norm(c) for c in rows[header_idx]]
    header_set = {h for h in headers if h}
    profile = identify_profile(filename, header_set, sheet_name)

    # brand fallback from the filename (alpha words only) for files lacking a brand column
    stem = (filename or "").rsplit(".", 1)[0]
    brand_default = norm(" ".join(t for t in re.split(r"[ _\-]+", stem) if t.isalpha()))

    resolver = Resolver()
    records = build_records(rows, header_idx)
    kdps_rows: list[dict] = []
    line_no = 0
    blank_cells = 0
    for rec in records:
        mapped = map_record(rec, profile, resolver, brand_default)
        if mapped is None:
            continue
        line_no += 1
        row, blanks = mapped
        blank_cells += len(blanks)
        kdps_rows.append({"line_no": line_no, "data": row, "blanks": blanks})

    reviews = list(resolver.misses.values())
    return {
        "profile_code": profile["code"],
        "profile_name": profile["name"],
        "archetype": profile["archetype"],
        "brand_guess": brand_default,
        "meta": {
            "sheet": sheet_name, "header_row": header_idx,
            "headers": [h for h in headers if h], "source_rows": len(records),
            "truncated": truncated, "row_limit": MAX_ROWS,
        },
        "rows": kdps_rows,
        "reviews": reviews,
        "blank_cells": blank_cells,
    }
