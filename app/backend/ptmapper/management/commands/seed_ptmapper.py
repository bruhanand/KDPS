"""Seed the PT-mapper lookup tables from KDPS's real Master Sheet.

Idempotent. Loads:
  - ControlledValue (the allowed value of every derived column),
  - ItemTaxonomy (ITEM → suggested SUB CATEGORY / TYPE),
  - identity + alias Lookups for brand / colour / size / gender / fit,
  - a starter set of TaxonomyRules (keyword → ITEM, with gender/fit where invariant).

The aliases below are the *seed* of business judgement (which raw shade is which
KDPS bucket, which brand alias maps where). Misses found while mapping real files
flow into the review queue and grow these tables further — no code change needed.
Every alias is written only if its target is a real Master-Sheet value.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand

from ptmapper.engine import season_label
from ptmapper.models import ControlledValue, ItemTaxonomy, Lookup, TaxonomyRule

DIM_COLS = {
    0: "season",
    1: "brand",
    2: "color",
    3: "gender",
    4: "sub_category",
    5: "type",
    6: "item",
    7: "fit",
    8: "size",
    9: "gst",
}

SEASON_WINDOW_START = date(2025, 1, 1)
SEASON_WINDOW_MONTHS_AHEAD = 18


def rolling_season_values(today: date) -> set[str]:
    """Every month-season label from Jan-25 through ~18 months past `today`, so a
    season derived from any plausible invoice date always validates (the Master
    Sheet's own season column stops at Oct-26 and is unioned in separately)."""
    out: set[str] = set()
    y, m = SEASON_WINDOW_START.year, SEASON_WINDOW_START.month
    end_y, end_m = today.year, today.month
    end_m += SEASON_WINDOW_MONTHS_AHEAD
    end_y, end_m = end_y + (end_m - 1) // 12, (end_m - 1) % 12 + 1
    while (y, m) <= (end_y, end_m):
        out.add(season_label(date(y, m, 1)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


BRAND_ALIASES = {
    "FM": "FLYING MACHINE",
    "PJ": "PETER ENGLAND",
    "PE": "PETER ENGLAND",
    "GO COLORS": "GOCOLORS",
    "GO COLOURS": "GOCOLORS",
    "BLACKBERRY": "BLACKBERRYS",
    "BLACKBERRY'S": "BLACKBERRYS",
    "VH": "VAN HEUSEN",
    "AS": "ALLEN SOLLY",
    "LP": "LOUIS PHILIPPE",
    "US POLO": "U S POLO ASSN",
    "USPOLO": "U S POLO ASSN",
    "U.S. POLO ASSN": "U S POLO ASSN",
    "JOCKEY PARAS": "JOCKEY",
    "JOCKEY NARAYANI": "JOCKEY",
    "JOCKEY NARVADA": "JOCKEY",
    "JOCKEY DD SALES": "JOCKEY",
    "SPYKAR": "SPYKAR",
    "KILLER JUNIOR": "KILLER",
    "JUNIOR KILLER": "KILLER",
}

# Brand shade string → one of KDPS's ~18 real colour buckets. (PREMIUM / ECONOMY /
# MEDIUM are price tiers that already live in the COLOR vocabulary and pass through.)
COLOR_ALIASES = {
    # BLUE family
    "LIGHT BLUE": "BLUE",
    "DARK BLUE": "BLUE",
    "SKY BLUE": "BLUE",
    "SKY": "BLUE",
    "ROYAL BLUE": "BLUE",
    "ROYAL": "BLUE",
    "MID BLUE": "BLUE",
    "BLUE BLACK": "BLUE",
    # NB: no bare "DENIM" alias — "DENIM" is as often a fabric/category as a shade, and
    # some files expose a product group in the colour column. "DENIM BLUE"/"DENIM BLU"
    # are unambiguous shades and stay.
    "DENIM BLUE": "BLUE",
    "DENIM BLU": "BLUE",
    "BLUE DN": "BLUE",
    "L BLU": "BLUE",
    "BL": "BLUE",
    "INDIGO": "BLUE",
    "INDIGO BLUE": "BLUE",
    "INDIGO MEL": "BLUE",
    "MID INDIGO": "BLUE",
    "DARK INDIGO BLUE": "BLUE",
    "DEEP INDIGO BLUE": "BLUE",
    "LIGHT INDIGO": "BLUE",
    "SULPHUR BLUE": "BLUE",
    "SULPHUR": "BLUE",
    "AIRFORCE": "BLUE",
    "AIR FORCE": "BLUE",
    "AIRFORCE BLUE": "BLUE",
    "BT AIRFORCE": "BLUE",
    "POWDER BLUE": "BLUE",
    "POWDER": "BLUE",
    "CORN BLUE": "BLUE",
    "COBALT": "BLUE",
    "ELECTRIC BLUE": "BLUE",
    "STEEL BLUE": "BLUE",
    "ICE BLUE": "BLUE",
    "AQUA BLUE": "BLUE",
    "DENIM BLU DN": "BLUE",
    # NAVY
    "NAVY BLUE": "NAVY",
    "TNAVY": "NAVY",
    "NVY": "NAVY",
    "DARK NAVY": "NAVY",
    "INK BLUE": "NAVY",
    "INK": "NAVY",
    "MIDNIGHT": "NAVY",
    "MIDNIGHT BLUE": "NAVY",
    "NAVI": "NAVY",
    # TEAL
    "TEAL BLUE": "TEAL",
    "TEAL GREEN": "TEAL",
    "TURQUOISE": "TEAL",
    "TURQUOISE BLUE": "TEAL",
    "TURQ": "TEAL",
    "PEACOCK": "TEAL",
    "PEACOCK BLUE": "TEAL",
    "PEACOCK GREEN": "TEAL",
    "AQUA": "TEAL",
    "AQUA GREEN": "TEAL",
    "CYAN": "TEAL",
    # GREEN
    "SEA GREEN": "GREEN",
    "PISTA": "GREEN",
    "PISTA GREEN": "GREEN",
    "LEAF GREEN": "GREEN",
    "LIME": "GREEN",
    "LIME GREEN": "GREEN",
    "BOTTLE GREEN": "GREEN",
    "DARK GREEN": "GREEN",
    "LIGHT GREEN": "GREEN",
    "FOREST GREEN": "GREEN",
    "FOREST": "GREEN",
    "PARROT GREEN": "GREEN",
    "PARROT": "GREEN",
    "EMERALD": "GREEN",
    "MINT": "GREEN",
    "MINT GREEN": "GREEN",
    "FERN": "GREEN",
    "KIWI": "GREEN",
    "NEON GREEN": "GREEN",
    "APPLE GREEN": "GREEN",
    "GREEN MEL": "GREEN",
    # OLIVE
    "OLIVE GREEN": "OLIVE",
    "ARMY": "OLIVE",
    "ARMY GREEN": "OLIVE",
    "MILITARY": "OLIVE",
    "MILITARY GREEN": "OLIVE",
    "MOSS": "OLIVE",
    "MOSS GREEN": "OLIVE",
    "MEHENDI": "OLIVE",
    "MEHANDI": "OLIVE",
    "KHAKI": "OLIVE",
    "KHAKHI": "OLIVE",
    "DARK OLIVE": "OLIVE",
    "OIL GREEN": "OLIVE",
    # RED
    "BRIGHT RED": "RED",
    "DARK RED": "RED",
    "CHERRY": "RED",
    "CHERRY RED": "RED",
    "SCARLET": "RED",
    "CRIMSON": "RED",
    "BLOOD RED": "RED",
    "FERRARI RED": "RED",
    "TOMATO": "RED",
    "TOMATO RED": "RED",
    "CHILLI": "RED",
    "CHILLI RED": "RED",
    # MAROON
    "WINE": "MAROON",
    "WINE RED": "MAROON",
    "DEEP MAROON": "MAROON",
    "DARK MAROON": "MAROON",
    "BURGUNDY": "MAROON",
    "MEHROON": "MAROON",
    "MAHROON": "MAROON",
    "DK WNE": "MAROON",
    "WNE": "MAROON",
    "OXBLOOD": "MAROON",
    "CLARET": "MAROON",
    # ORANGE
    "PEACH": "ORANGE",
    "DEEP PEACH": "ORANGE",
    "LIGHT PEACH": "ORANGE",
    "LT PEACH": "ORANGE",
    "LT. PEACH": "ORANGE",
    "CORAL": "ORANGE",
    "CORAL ORANGE": "ORANGE",
    "TANGERINE": "ORANGE",
    "APRICOT": "ORANGE",
    "SALMON": "ORANGE",
    "NEON ORANGE": "ORANGE",
    "CARROT": "ORANGE",
    "GAJARI": "ORANGE",
    # RUST
    "BRICK": "RUST",
    "BRICK RED": "RUST",
    "COPPER": "RUST",
    "TERRACOTTA": "RUST",
    "BURNT ORANGE": "RUST",
    "RUST ORANGE": "RUST",
    "CLAY": "RUST",
    # PINK
    "BLUSH": "PINK",
    "BABY PINK": "PINK",
    "LIGHT PINK": "PINK",
    "HOT PINK": "PINK",
    "DARK PINK": "PINK",
    "MEDIUM PINK": "PINK",
    "RANI": "PINK",
    "RANI PINK": "PINK",
    "FUCHSIA": "PINK",
    "FUSCHIA": "PINK",
    "MAGENTA": "PINK",
    "LIPSTICK": "PINK",
    "LIPSTICK PINK": "PINK",
    "ROSE": "PINK",
    "ROSE PINK": "PINK",
    "DUSTY ROSE": "PINK",
    "DUSTY PINK": "PINK",
    "PASTEL PINK": "PINK",
    "FLAMINGO": "PINK",
    "ONION": "PINK",
    "ONION PINK": "PINK",
    "CARNATION": "PINK",
    "BUBBLEGUM": "PINK",
    "SALMON PINK": "PINK",
    # PURPLE
    "LILAC": "PURPLE",
    "LAVENDER": "PURPLE",
    "LAVENDAR": "PURPLE",
    "MAUVE": "PURPLE",
    "VIOLET": "PURPLE",
    "PLUM": "PURPLE",
    "GRAPE": "PURPLE",
    "AUBERGINE": "PURPLE",
    "EGGPLANT": "PURPLE",
    "ORCHID": "PURPLE",
    "AMETHYST": "PURPLE",
    # YELLOW
    "MUSTARD": "YELLOW",
    "LEMON": "YELLOW",
    "LEMON YELLOW": "YELLOW",
    "GOLD": "YELLOW",
    "GOLDEN": "YELLOW",
    "YELLOW OCHRE": "YELLOW",
    "OCHRE": "YELLOW",
    "CORN": "YELLOW",
    "CORN YELLOW": "YELLOW",
    "SUNFLOWER": "YELLOW",
    "MANGO": "YELLOW",
    "HONEY": "YELLOW",
    "AMBER": "YELLOW",
    "CANARY": "YELLOW",
    "TURMERIC": "YELLOW",
    # BROWN
    "COFFEE": "BROWN",
    "CHOCOLATE": "BROWN",
    "CHOCO": "BROWN",
    "TAN": "BROWN",
    "CAMEL": "BROWN",
    "MOCHA": "BROWN",
    "COCOA": "BROWN",
    "WALNUT": "BROWN",
    "TOBACCO": "BROWN",
    "LIGHT BROWN": "BROWN",
    "DARK BROWN": "BROWN",
    "TEA LEAF": "BROWN",
    "TEAK": "BROWN",
    "RUST BROWN": "BROWN",
    "MUD": "BROWN",
    "MUD BROWN": "BROWN",
    "ESPRESSO": "BROWN",
    "HAZEL": "BROWN",
    "TAUPE": "BROWN",
    # CREAM
    "BEIGE": "CREAM",
    "LIGHT BEIGE": "CREAM",
    "LT BEIGE": "CREAM",
    "LT. BEIGE": "CREAM",
    "OFF WHITE": "CREAM",
    "OFF-WHITE": "CREAM",
    "IVORY": "CREAM",
    "ECRU": "CREAM",
    "FAWN": "CREAM",
    "SAND": "CREAM",
    "OATS": "CREAM",
    "OAT": "CREAM",
    "OATMEAL": "CREAM",
    "NUDE": "CREAM",
    "SKIN": "CREAM",
    "NATURAL": "CREAM",
    "CHALK": "CREAM",
    "PEARL": "CREAM",
    "VANILLA": "CREAM",
    "LINEN": "CREAM",
    "BONE": "CREAM",
    "WHEAT": "CREAM",
    "CHAMPAGNE": "CREAM",
    "BUFF": "CREAM",
    "BISCUIT": "CREAM",
    # CHIKU (tan-khaki bucket KDPS keeps distinct)
    "CHIKOO": "CHIKU",
    "CHICOO": "CHIKU",
    "CHIKKU": "CHIKU",
    # WHITE
    "PURE WHITE": "WHITE",
    "BRIGHT WHITE": "WHITE",
    "MILK": "WHITE",
    "MILKY WHITE": "WHITE",
    "SNOW": "WHITE",
    "SNOW WHITE": "WHITE",
    "CLOUD": "WHITE",
    "OPTIC WHITE": "WHITE",
    "WHITE MEL": "WHITE",
    # GREY
    "GRAY": "GREY",
    "GREY MEL": "GREY",
    "GREY MELANGE": "GREY",
    "MELANGE GREY": "GREY",
    "M GREY": "GREY",
    "MID GREY": "GREY",
    "LIGHT GREY": "GREY",
    "DARK GREY": "GREY",
    "CHARCOAL": "GREY",
    "CHARCOAL GREY": "GREY",
    "SLV GY": "GREY",
    "SILVER": "GREY",
    "SILVER GREY": "GREY",
    "STONE": "GREY",
    "STONE GREY": "GREY",
    "ASH": "GREY",
    "ASH GREY": "GREY",
    "SMOKE": "GREY",
    "SMOKE GREY": "GREY",
    "STEEL": "GREY",
    "STEEL GREY": "GREY",
    "ANTHRACITE": "GREY",
    "GRINDLE": "GREY",
    "MILANGE": "GREY",
    "MELANGE": "GREY",
    "GRAPHITE": "GREY",
    "SLATE": "GREY",
    "GUNMETAL": "GREY",
    "CARBON": "GREY",
    # BLACK
    "JET BLACK": "BLACK",
    "PURE BLACK": "BLACK",
    "PITCH BLACK": "BLACK",
    "DENIM BLACK": "BLACK",
    "BLACK MEL": "BLACK",
    "COAL": "BLACK",
}

# Most size variants are handled by normalize_size(); these are the few word forms.
SIZE_ALIASES = {
    "FREE SIZE": "FREE SIZE",
    "STANDARD": "FREE SIZE",
}

# Brand-level default GENDER, used only as the LAST fallback when a row has no
# gender column, no gender word in the description, and no rule default (see
# engine._map_taxonomy). Seed only brands that are unambiguously single-gender in
# KDPS's assortment; mixed brands (Allen Solly, Van Heusen, USPA, Jockey…) stay
# unseeded so a wrong default is never silently applied.
BRAND_GENDER = {
    "PETER ENGLAND": "MALE",
    "LOUIS PHILIPPE": "MALE",
    "BLACKBERRYS": "MALE",
    "MUFTI": "MALE",
    "GOCOLORS": "FEMALE",
}

# Brand fit-column value → KDPS master FIT.
FIT_ALIASES = {
    "SLIM FIT": "SLIM",
    "REGULAR FIT": "REGULAR",
    "COMFORT FIT": "RELAXED",
    "COMFORT": "RELAXED",
    "RELAXED FIT": "RELAXED",
    "SKINNY FIT": "SKINNY",
    "STRAIGHT FIT": "STRAIGHT",
    "BOOTCUT FIT": "BOOTCUT",
    "TAILORED FIT": "TAILORED",
    "CLASSIC": "CLASSIC FIT",
    "SUPER SLIM FIT": "SUPER SLIM",
    "SLIM TAPERED": "SLIM TEPAR",
    "SLIM STRAIGHT FIT": "SLIM STRAIGHT",
    "REGULAR STRAIGHT FIT": "REGULAR STRAIGHT",
    "CREW": "CREW NECK",
    "ROUND": "ROUND NECK",
    "POLO": "POLO NECK",
    # Peter England / ABFRL coded FIT TYPE ("PJ RG OCTANEMIDSTR"): token 2 is the
    # fit family — RG = Regular, SL = Slim (see engine.fit_code_candidates).
    # NB: no "SNUG" alias — the Master FIT list has no SNUG and rows carrying it
    # ("PC SL Snug") already resolve via the SL token; mapping it would be a guess.
    "RG": "REGULAR",
    "SL": "SLIM",
    # NB: no "V NECK" alias — the Master FIT list has no V-neck, and mapping it to
    # ROUND NECK would be deterministically wrong. Leave it for the review queue.
}

GENDER_MAP = {
    "MALE": "MALE",
    "MEN": "MALE",
    "MENS": "MALE",
    "MAN": "MALE",
    "M": "MALE",
    "GENTS": "MALE",
    "GENT": "MALE",
    "BOYS": "KIDS MALE",
    "BOY": "KIDS MALE",
    "KIDS MALE": "KIDS MALE",
    "KIDS BOYS": "KIDS MALE",
    "JUNIOR BOYS": "KIDS MALE",
    "FEMALE": "FEMALE",
    "WOMEN": "FEMALE",
    "WOMENS": "FEMALE",
    "WOMAN": "FEMALE",
    "LADIES": "FEMALE",
    "LADY": "FEMALE",
    "F": "FEMALE",
    "GIRLS": "KIDS FEMALE",
    "GIRL": "KIDS FEMALE",
    "KIDS FEMALE": "KIDS FEMALE",
    "KIDS GIRLS": "KIDS FEMALE",
    "JUNIOR GIRLS": "KIDS FEMALE",
    "UNISEX": "UNISEX",
    "KIDS": "UNISEX",
    "KID": "UNISEX",
    "INFANT": "UNISEX",
}

# (pattern, gender, item, fit). SUB CATEGORY / TYPE auto-fill from the ITEM→helper.
# gender here is only a default for invariant items — a gender column or a gender word
# in the description overrides it (see engine._map_taxonomy).
RULE_SEED = [
    # --- top wear
    ("T-SHIRT", "", "T-SHIRT", ""),
    ("T SHIRT", "", "T-SHIRT", ""),
    ("TSHIRT", "", "T-SHIRT", ""),
    ("TEE", "", "T-SHIRT", ""),
    ("POLO", "", "T-SHIRT", "POLO NECK"),
    ("FORMAL SHIRT", "", "SHIRT", ""),
    ("CASUAL SHIRT", "", "SHIRT", ""),
    ("SHIRT", "", "SHIRT", ""),
    ("KURTI", "FEMALE", "KURTI", ""),
    ("TUNIC", "FEMALE", "KURTI", ""),
    ("KURTA SET", "", "KURTI SET", ""),
    ("KURTI SET", "FEMALE", "KURTI SET", ""),
    ("KURTA", "", "KURTA", ""),
    ("KURTHA", "", "KURTA", ""),
    ("CROP TOP", "FEMALE", "CROP TOP", ""),
    ("CAMISOLE", "FEMALE", "CAMISOLE", ""),
    ("CAMI", "FEMALE", "CAMISOLE", ""),
    ("BLOUSE", "FEMALE", "BLOUSE", ""),
    ("TOP", "", "TOP", ""),
    ("SWEATSHIRT", "", "SWEATSHIRT", ""),
    ("SWEAT SHIRT", "", "SWEATSHIRT", ""),
    ("HOODIE", "", "SWEATSHIRT", ""),
    ("SWEATER", "", "SWEATER", ""),
    ("PULLOVER", "", "SWEATER", ""),
    ("CARDIGAN", "", "CARDIGAN", ""),
    ("BLAZER", "", "BLAZER", ""),
    ("WAISTCOAT", "", "BLAZER", ""),
    ("NEHRU JACKET", "MALE", "NEHRU JACKET", ""),
    ("JACKET", "", "JACKET", ""),
    ("SHACKET", "", "SHACKET", ""),
    ("WINDCHEATER", "", "WINDCHEATER", ""),
    ("WIND CHEATER", "", "WINDCHEATER", ""),
    ("RAINCOAT", "", "RAINCOAT", ""),
    ("THERMAL", "", "THERMAL", ""),
    # --- one-piece
    ("GOWN", "FEMALE", "GOWN", ""),
    ("DRESS", "FEMALE", "DRESSES", ""),
    ("FROCK", "KIDS FEMALE", "FROCK", ""),
    ("MIDI", "FEMALE", "MIDY", ""),
    ("MIDY", "FEMALE", "MIDY", ""),
    ("JUMPSUIT", "", "JUMP SUIT", ""),
    ("JUMP SUIT", "", "JUMP SUIT", ""),
    ("DUNGAREE", "", "DUNGAREE", ""),
    ("NIGHTY", "FEMALE", "NIGHTY", ""),
    ("SAREE", "FEMALE", "SAREE", ""),
    ("LEHENGA", "FEMALE", "LEHENGA", ""),
    ("SALWAR", "FEMALE", "SALWAR SUIT", ""),
    ("SHERWANI", "MALE", "SHERWANI", ""),
    # --- bottom wear
    ("JEANS", "", "JEANS", ""),
    ("JEAN", "", "JEANS", ""),
    ("JEGGING", "FEMALE", "JEGGING", ""),
    ("JEGGINGS", "FEMALE", "JEGGING", ""),
    ("TROUSER", "", "TROUSER", ""),
    ("TROUSERS", "", "TROUSER", ""),
    ("CHINO", "", "TROUSER", ""),
    ("FORMAL PANT", "", "TROUSER", ""),
    ("PANT", "", "TROUSER", ""),
    ("TRACK PANT", "", "JOGGER", "TRACK PANT"),
    ("TRACKPANT", "", "JOGGER", "TRACK PANT"),
    ("JOGGER", "", "JOGGER", ""),
    ("JOGGERS", "", "JOGGER", ""),
    ("LOWER", "", "LOWER", ""),
    ("LOWERS", "", "LOWER", ""),
    ("SHORTS", "", "SHORTS", ""),
    ("BERMUDA", "", "SHORTS", "BERMUDA"),
    ("CAPRI", "", "CAPRI", ""),
    ("CAPRIS", "", "CAPRI", ""),
    ("LEGGING", "FEMALE", "LEGGING", ""),
    ("LEGGINGS", "FEMALE", "LEGGING", ""),
    ("PALAZZO", "FEMALE", "PALAZZO", ""),
    ("PALAZZO SET", "FEMALE", "PALAZZO SET", ""),
    ("PLAZO", "FEMALE", "PALAZZO", ""),
    ("PLAZZO", "FEMALE", "PALAZZO", ""),
    ("PLAZOO", "FEMALE", "PALAZZO", ""),
    ("SKIRT", "FEMALE", "SKIRT", ""),
    ("CARGO", "", "CARGO", ""),
    ("DHOTI", "MALE", "DHOTI", ""),
    ("PATIALA", "FEMALE", "PATIALA", ""),
    ("PETTICOAT", "FEMALE", "PETTICOAT", ""),
    # --- full set
    ("CO-ORD", "", "CO-ORD SET", ""),
    ("CO ORD", "", "CO-ORD SET", ""),
    ("COORD", "", "CO-ORD SET", ""),
    ("NIGHT SUIT", "", "NIGHT SUIT", ""),
    ("NIGHTSUIT", "", "NIGHT SUIT", ""),
    ("TRACKSUIT", "", "TRACKSUIT", ""),
    ("TRACK SUIT", "", "TRACKSUIT", ""),
    ("BABA SUIT", "KIDS MALE", "BABA SUIT", ""),
    ("PANT SET", "", "CO-ORD SET", "PANT SET"),
    ("SHORTS SET", "", "CO-ORD SET", "SHORTS SET"),
    ("DRESS MATERIAL", "", "DRESS MATERIAL", ""),
    ("SUIT", "", "SUIT", ""),
    # --- innerwear
    ("BRIEF", "", "BRIEF", ""),
    ("TRUNK", "MALE", "BRIEF", "TRUNK"),
    ("BOXER", "", "BRIEF", "BOXER"),
    ("VEST", "", "VEST", ""),
    ("BRA", "FEMALE", "BRA", ""),
    ("PANTIE", "FEMALE", "PANTIE", ""),
    ("PANTY", "FEMALE", "PANTIE", ""),
    ("BLOOMER", "", "BLOOMER", ""),
    ("SOCKS", "", "SOCKS", ""),
    ("SOCK", "", "SOCKS", ""),
    # --- accessories
    ("BELT", "", "BELT", ""),
    ("WALLET", "", "WALLET", ""),
    ("CAP", "", "CAP", ""),
    ("HANDBAG", "", "HANDBAG", ""),
    ("HAND BAG", "", "HANDBAG", ""),
    ("BACKPACK", "", "BACKPACK", ""),
    ("DUFFLE", "", "DUFFLE BAG", ""),
    ("DUPATTA", "FEMALE", "DUPATTA", ""),
    ("STOLE", "", "STOLE", ""),
    ("SCARF", "", "SCARVES", ""),
    ("SCARVES", "", "SCARVES", ""),
    ("MUFFLER", "", "MUFFLER", ""),
    ("TIE", "", "TIES & BOWTIE", ""),
    ("HANDKERCHIEF", "", "HANDKERCHIEF", ""),
    ("POCKET SQUARE", "", "POCKET SQUARE", ""),
    ("SHOES", "", "SHOES", ""),
    ("SLIPPER", "", "SLIPPERS", ""),
    ("JUTI", "", "JUTI", ""),
    ("TOWEL", "", "TOWEL", ""),
    ("BEDSHEET", "", "BEDSHEET", ""),
    ("PERFUME", "", "PERFUME", ""),
    ("DEODRANT", "", "DEODRENT", ""),
    ("DEODORANT", "", "DEODRENT", ""),
    # --- ethnic top variants
    ("INDO WESTERN", "", "KURTI SET", "INDO WESTERN"),
    # --- Madura SAP glued material codes the substring matcher can't split
    ("TROUSR", "", "TROUSER", ""),
    ("FGKTROUSR", "", "TROUSER", ""),
    ("FGSUIT", "", "SUIT", ""),
    ("FGTRAKPNT", "", "JOGGER", "TRACK PANT"),
    ("FGTOPS", "", "TOP", ""),
    ("FGCKNTOP", "", "TOP", ""),
    ("FGTOP", "", "TOP", ""),
]


def cv(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val).strip()


def _pick_valid(cell: str, valid: set[str]) -> str:
    """From a Master helper cell that may hold several '/'-separated options
    ('FORMAL / CASUAL/ PARTY WEAR'), return the first that resolves to a real value
    (exact, else a Master value that starts with the token: 'CASUAL'→'CASUAL WEAR')."""
    if not cell:
        return ""
    for tok in re.split(r"[/,]", cell):
        tok = tok.strip()
        if not tok:
            continue
        if tok in valid:
            return tok
        for v in sorted(valid):  # sorted → deterministic when a token prefixes >1 value
            if v.startswith(tok):
                return v
    return ""


def _add_lookup(dim: str, key: str, target: str) -> None:
    # Seed rows are global (brand=""); brand-scoped rules are learned from corrections.
    Lookup.objects.update_or_create(
        dimension=dim,
        source_key=key.upper().strip(),
        brand="",
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
    item_rows: dict[str, tuple[str, str]] = {}
    for r in rows[1:]:
        for ci, dim in DIM_COLS.items():
            if ci < len(r):
                v = cv(r[ci])
                if v:
                    dim_values[dim].add(v)
        # ITEM (col 6) → suggested SUB CATEGORY (col 10) / TYPE (col 11) on the same row
        if len(r) > 6:
            item = cv(r[6])
            if item:
                sub = cv(r[10]) if len(r) > 10 else ""
                typ = cv(r[11]) if len(r) > 11 else ""
                item_rows[item] = (sub, typ)
    return dim_values, item_rows


def _seed_controlled(
    dim_values: dict[str, set[str]], item_rows: dict[str, tuple[str, str]]
) -> None:
    for dim, values in dim_values.items():
        for v in values:
            ControlledValue.objects.get_or_create(dimension=dim, value=v)
    sub_set, type_set = dim_values["sub_category"], dim_values["type"]
    for item, (sub_raw, type_raw) in item_rows.items():
        ItemTaxonomy.objects.update_or_create(
            item=item,
            defaults={
                "sub_category": _pick_valid(sub_raw, sub_set),
                "type": _pick_valid(type_raw, type_set),
            },
        )


def _seed_aliased(dim: str, identity: set[str], aliases: dict[str, str], valid: set[str]) -> None:
    for v in identity:
        _add_lookup(dim, v, v)
    for alias, target in aliases.items():
        if target in valid:
            _add_lookup(dim, alias, target)


def _seed_lookups(dim_values: dict[str, set[str]]) -> None:
    _seed_aliased("brand", dim_values["brand"], BRAND_ALIASES, dim_values["brand"])
    _seed_aliased("color", dim_values["color"], COLOR_ALIASES, dim_values["color"])
    _seed_aliased("size", dim_values["size"], SIZE_ALIASES, dim_values["size"])
    _seed_aliased("fit", dim_values["fit"], FIT_ALIASES, dim_values["fit"])
    for alias, target in GENDER_MAP.items():
        if target in dim_values["gender"]:
            _add_lookup("gender", alias, target)
    # brand → default gender (an engine fallback dimension, not a Master column)
    for brand, gender in BRAND_GENDER.items():
        if brand in dim_values["brand"] and gender in dim_values["gender"]:
            _add_lookup("brand_gender", brand, gender)


# Per-rule SUB CATEGORY override, for items that span categories so the single
# ITEM→helper row would otherwise collapse the distinction (a SHIRT defaults to
# FORMAL WEAR in the Master helper, but a "casual shirt" must stay CASUAL WEAR).
SUB_OVERRIDE = {
    "FORMAL SHIRT": "FORMAL WEAR",
    "CASUAL SHIRT": "CASUAL WEAR",
    "SHIRT": "CASUAL WEAR",
    "FORMAL PANT": "FORMAL WEAR",
}


def _seed_rules(dim_values: dict[str, set[str]]) -> int:
    item_set, gender_set, fit_set = dim_values["item"], dim_values["gender"], dim_values["fit"]
    sub_set = dim_values["sub_category"]
    made_rules = 0
    for pattern, gender, item, fit in RULE_SEED:
        if item and item not in item_set:
            continue  # never seed a rule whose ITEM is not a real Master value
        sub = SUB_OVERRIDE.get(pattern, "")
        TaxonomyRule.objects.update_or_create(
            pattern=pattern,
            defaults={
                "gender": gender if gender in gender_set else "",
                # explicit SUB CATEGORY only where the item spans categories; otherwise
                # blank → auto-filled from the ITEM→helper at map time.
                "sub_category": sub if sub in sub_set else "",
                "type": "",
                "item": item,
                "fit": fit if fit in fit_set else "",
                "priority": len(pattern),
            },
        )
        made_rules += 1
    return made_rules


def _merge_vocabularies(
    sources: list[tuple[Path, dict[str, set[str]], dict[str, tuple[str, str]]]],
) -> tuple[dict[str, set[str]], dict[str, tuple[str, str]]]:
    """Union the dimension values of every Master Sheet read; for the ITEM →
    (SUB CATEGORY, TYPE) helper the FIRST source (the canonical file) wins."""
    dim_values: dict[str, set[str]] = {d: set() for d in DIM_COLS.values()}
    item_rows: dict[str, tuple[str, str]] = {}
    for _, dims, items in sources:
        for d, vals in dims.items():
            dim_values[d] |= vals
        for item, helper in items.items():
            item_rows.setdefault(item, helper)
    return dim_values, item_rows


class Command(BaseCommand):
    help = "Seed PT-mapper controlled vocabulary + lookup tables from the Master Sheet."

    def add_arguments(self, parser) -> None:
        repo_root = Path(settings.BASE_DIR).parent.parent
        data = repo_root / "docs" / "data-from-kdps"
        # Canonical first (its Master Sheet carries the Excel data-validation
        # dropdowns the UI replicates); the legacy sheet is unioned in so nothing
        # already seeded from it ever disappears.
        parser.add_argument(
            "--path", default=str(data / "05-reference-data" / "pt-file-format.xlsx")
        )
        parser.add_argument("--extra-path", default=str(data / "KDPS PT FILE SHEET.xlsx"))

    def handle(self, *args, **opts) -> None:
        paths = [Path(opts["path"]), Path(opts["extra_path"])]
        sources = []
        for p in paths:
            if not p.exists():
                self.stderr.write(f"Master Sheet not found at {p} — skipped.")
                continue
            dims, items = _extract_vocabulary(_load_master_sheet(p))
            sources.append((p, dims, items))
        if not sources:
            self.stderr.write("No Master Sheet found — nothing seeded.")
            return
        dim_values, item_rows = _merge_vocabularies(sources)
        if len(sources) == 2:
            for dim in DIM_COLS.values():
                a, b = sources[0][1].get(dim, set()), sources[1][1].get(dim, set())
                if a != b:
                    self.stdout.write(
                        f"  [{dim}] master sheets differ: "
                        f"only-canonical={sorted(a - b)!r} only-legacy={sorted(b - a)!r}"
                    )

        # Season is date-derived at map time, so the vocabulary must always cover a
        # rolling window (the sheets' own season column ends at a fixed month).
        dim_values["season"] |= rolling_season_values(date.today())

        _seed_controlled(dim_values, item_rows)
        _seed_lookups(dim_values)
        made_rules = _seed_rules(dim_values)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded controlled values ({sum(len(v) for v in dim_values.values())}) "
                f"from {len(sources)} sheet(s), item taxonomy ({len(item_rows)}), lookups "
                f"(brand +{len(BRAND_ALIASES)}, color +{len(COLOR_ALIASES)}, "
                f"fit +{len(FIT_ALIASES)}, brand_gender +{len(BRAND_GENDER)} aliases), "
                f"taxonomy rules ({made_rules})."
            )
        )
