"""Seed the PT-mapper lookup tables from KDPS's real Master Sheet.

Idempotent. Loads:
  - ControlledValue (the allowed value of every derived column),
  - ItemTaxonomy (ITEM → suggested SUB CATEGORY / TYPE),
  - identity + alias Lookups for brand / colour / size / gender,
  - a starter set of TaxonomyRules (keyword → 5-axis grid).

Misses found while mapping real files flow into the review queue and grow these
tables further — no code change needed.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand

from ptmapper.models import ControlledValue, ItemTaxonomy, Lookup, TaxonomyRule

DIM_COLS = {
    0: "season", 1: "brand", 2: "color", 3: "gender", 4: "sub_category",
    5: "type", 6: "item", 7: "fit", 8: "size", 9: "gst",
}

BRAND_ALIASES = {
    "FM": "FLYING MACHINE", "PJ": "PETER ENGLAND", "GO COLORS": "GO COLOURS",
    "BLACKBERRYS": "BLACKBERRY", "MADURA": "PETER ENGLAND",
}
COLOR_ALIASES = {
    "LIGHT BLUE": "BLUE", "DARK BLUE": "BLUE", "SKY BLUE": "BLUE", "NAVY BLUE": "NAVY",
    "INDIGO": "BLUE", "INDIGO MEL": "BLUE", "TNAVY": "NAVY", "OFF WHITE": "WHITE",
    "MUSTARD": "YELLOW", "WINE": "MAROON", "PEACH": "ORANGE", "BEIGE": "CREAM",
    "KHAKI": "OLIVE", "TEAL BLUE": "TEAL", "AQUA": "BLUE", "GREEN MEL": "GREEN",
}
SIZE_ALIASES = {
    "FREE SIZE": "FREE", "F": "FREE", "FS": "FREE", "1 MTR.": "FREE",
}
GENDER_MAP = {
    "MALE": "MALE", "MEN": "MALE", "MENS": "MALE", "MAN": "MALE", "M": "MALE", "GENTS": "MALE",
    "BOYS": "KIDS MALE", "BOY": "KIDS MALE", "KIDS MALE": "KIDS MALE",
    "FEMALE": "FEMALE", "WOMEN": "FEMALE", "WOMENS": "FEMALE", "WOMAN": "FEMALE",
    "LADIES": "FEMALE", "GIRLS": "KIDS FEMALE", "GIRL": "KIDS FEMALE",
    "KIDS FEMALE": "KIDS FEMALE", "UNISEX": "UNISEX", "KIDS": "UNISEX",
}

# (pattern, gender, sub_category, type, item, fit) — filtered to valid Master values at load.
RULE_SEED = [
    ("TRACK PANT", "", "SPORTS WEAR", "BOTTOM WEAR", "TRACK PANT", ""),
    ("TRACKPANT", "", "SPORTS WEAR", "BOTTOM WEAR", "TRACK PANT", ""),
    ("JEANS", "", "CASUAL WEAR", "BOTTOM WEAR", "JEANS", ""),
    ("T-SHIRT", "", "CASUAL WEAR", "TOP WEAR", "T-SHIRT", ""),
    ("T SHIRT", "", "CASUAL WEAR", "TOP WEAR", "T-SHIRT", ""),
    ("TSHIRT", "", "CASUAL WEAR", "TOP WEAR", "T-SHIRT", ""),
    ("TROUSER", "", "FORMAL WEAR", "BOTTOM WEAR", "TROUSER", ""),
    ("FORMAL SHIRT", "", "FORMAL WEAR", "TOP WEAR", "SHIRT", ""),
    ("SHIRT", "", "CASUAL WEAR", "TOP WEAR", "SHIRT", ""),
    ("PYJAMA", "", "NIGHTWEAR", "BOTTOM WEAR", "PYJAMA", ""),
    ("PALAZZO", "", "CASUAL WEAR", "BOTTOM WEAR", "PALAZZO", ""),
    ("KURTI", "", "CASUAL WEAR", "TOP WEAR", "KURTI", ""),
    ("KURTA", "", "CASUAL WEAR", "TOP WEAR", "KURTA", ""),
    ("SAREE", "", "PARTY WEAR", "ONE-PIECE", "SAREE", ""),
    ("BRIEF", "", "INNERWEAR", "BOTTOM WEAR", "BRIEF", ""),
    ("BRA", "", "INNERWEAR", "TOP WEAR", "BRA", ""),
    ("CAMISOLE", "", "INNERWEAR", "TOP WEAR", "CAMISOLE", ""),
    ("SKIRT", "", "CASUAL WEAR", "BOTTOM WEAR", "SKIRT", ""),
    ("CAPRI", "", "CASUAL WEAR", "BOTTOM WEAR", "CAPRI", ""),
    ("CARGO", "", "CASUAL WEAR", "BOTTOM WEAR", "CARGO", ""),
    ("SHORTS", "", "CASUAL WEAR", "BOTTOM WEAR", "SHORTS", ""),
    ("BLAZER", "", "FORMAL WEAR", "TOP WEAR", "BLAZER", ""),
    ("BLOUSE", "", "CASUAL WEAR", "TOP WEAR", "BLOUSE", ""),
    ("FROCK", "", "PARTY WEAR", "ONE-PIECE", "FROCK", ""),
    ("DRESS", "", "PARTY WEAR", "ONE-PIECE", "DRESSES", ""),
    ("BELT", "", "ACCESSORIES", "ACCESSORIES", "BELT", ""),
    ("CAP", "", "ACCESSORIES", "ACCESSORIES", "CAP", ""),
    ("3 PCS SUIT", "", "PARTY WEAR", "FULL SET", "", ""),
    ("SUIT", "", "FORMAL WEAR", "FULL SET", "", ""),
    ("CO-ORD", "", "CASUAL WEAR", "FULL SET", "CO-ORD SET", ""),
    ("CROP TOP", "", "CASUAL WEAR", "TOP WEAR", "CROP TOP", ""),
    ("DUPATTA", "", "ACCESSORIES", "ACCESSORIES", "DUPATTA", ""),
    ("DUNGAREE", "", "CASUAL WEAR", "FULL SET", "DUNGAREE", ""),
]


def cv(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val).strip()


def first_token(val: str) -> str:
    return val.split("/")[0].strip() if val else val


def _add_lookup(dim: str, key: str, target: str) -> None:
    Lookup.objects.update_or_create(
        dimension=dim, source_key=key.upper().strip(),
        defaults={"target_value": target},
    )


def _load_master_sheet(path: Path) -> list[list]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ms = wb["Master Sheet"]
    rows = [list(r) for r in ms.iter_rows(values_only=True)]
    wb.close()
    return rows


def _extract_vocabulary(rows: list[list]) -> tuple[dict[str, set[str]], dict[str, tuple[str, str]]]:
    dim_values: dict[str, set[str]] = {d: set() for d in DIM_COLS.values()}
    item_tax: dict[str, tuple[str, str]] = {}
    for r in rows[1:]:
        for ci, dim in DIM_COLS.items():
            if ci < len(r):
                v = cv(r[ci])
                if v:
                    dim_values[dim].add(v)
        # ITEM (col 6) → suggested SUB CATEGORY (col 10) / TYPE (col 11)
        if len(r) > 6:
            item = cv(r[6])
            if item:
                sub = first_token(cv(r[10])) if len(r) > 10 else ""
                typ = first_token(cv(r[11])) if len(r) > 11 else ""
                item_tax[item] = (sub, typ)
    return dim_values, item_tax


def _seed_controlled(dim_values: dict[str, set[str]], item_tax: dict[str, tuple[str, str]]) -> None:
    for dim, values in dim_values.items():
        for v in values:
            ControlledValue.objects.get_or_create(dimension=dim, value=v)
    sub_set, type_set = dim_values["sub_category"], dim_values["type"]
    for item, (sub, typ) in item_tax.items():
        ItemTaxonomy.objects.update_or_create(
            item=item,
            defaults={
                "sub_category": sub if sub in sub_set else "",
                "type": typ if typ in type_set else "",
            },
        )


def _seed_lookups(dim_values: dict[str, set[str]]) -> None:
    for b in dim_values["brand"]:
        _add_lookup("brand", b, b)
    for alias, target in BRAND_ALIASES.items():
        if target in dim_values["brand"]:
            _add_lookup("brand", alias, target)
    for c in dim_values["color"]:
        _add_lookup("color", c, c)
    for alias, target in COLOR_ALIASES.items():
        if target in dim_values["color"]:
            _add_lookup("color", alias, target)
    for s in dim_values["size"]:
        _add_lookup("size", s, s)
    for alias, target in SIZE_ALIASES.items():
        if target in dim_values["size"]:
            _add_lookup("size", alias, target)
    for alias, target in GENDER_MAP.items():
        if target in dim_values["gender"]:
            _add_lookup("gender", alias, target)


def _seed_rules(dim_values: dict[str, set[str]]) -> int:
    item_set, gender_set, fit_set = dim_values["item"], dim_values["gender"], dim_values["fit"]
    sub_set, type_set = dim_values["sub_category"], dim_values["type"]
    made_rules = 0
    for pattern, gender, sub, typ, item, fit in RULE_SEED:
        if item and item not in item_set:
            continue
        if sub and sub not in sub_set:
            sub = ""
        if typ and typ not in type_set:
            typ = ""
        if gender and gender not in gender_set:
            gender = ""
        if fit and fit not in fit_set:
            fit = ""
        TaxonomyRule.objects.update_or_create(
            pattern=pattern,
            defaults={
                "gender": gender, "sub_category": sub, "type": typ,
                "item": item, "fit": fit, "priority": len(pattern),
            },
        )
        made_rules += 1
    return made_rules


class Command(BaseCommand):
    help = "Seed PT-mapper controlled vocabulary + lookup tables from the Master Sheet."

    def add_arguments(self, parser) -> None:
        repo_root = Path(settings.BASE_DIR).parent.parent
        default = repo_root / "docs" / "data-from-kdps" / "KDPS PT FILE SHEET.xlsx"
        parser.add_argument("--path", default=str(default))

    def handle(self, *args, **opts) -> None:
        path = Path(opts["path"])
        if not path.exists():
            self.stderr.write(f"Master Sheet not found at {path}")
            return
        rows = _load_master_sheet(path)
        dim_values, item_tax = _extract_vocabulary(rows)
        _seed_controlled(dim_values, item_tax)
        _seed_lookups(dim_values)
        made_rules = _seed_rules(dim_values)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded controlled values ({sum(len(v) for v in dim_values.values())}), "
            f"item taxonomy ({len(item_tax)}), lookups "
            f"(brand {len(dim_values['brand'])}, color {len(dim_values['color'])}, "
            f"size {len(dim_values['size'])}), taxonomy rules ({made_rules})."
        ))
