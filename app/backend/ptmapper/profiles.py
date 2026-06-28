"""Mapping profiles — engine config per brand-file *archetype* (not per brand).

A profile says: how to recognise the file, which sheet/header to read, and which
source column feeds each KDPS field. The generic ALIASES below cover the ~60-70%
"plain rename" fields for any file; a profile only overrides the parts an
archetype does differently (e.g. Ginesys hides colour/size inside CATEGORY3/4).
"""

from __future__ import annotations

# KDPS target Work Sheet columns, in order.
KDPS_COLUMNS = [
    "SEASON", "BRAND", "COLOR", "GENDER", "SUB CATEGORY", "TYPE", "ITEM", "FIT",
    "SIZE", "BARCODE", "DESIGN", "HSN", "QTY", "MRP", "BASIC", "P RATE",
    "INPUT TAX", "OUTPUT TAX", "NAG", "MARGIN", "SUGGESTED SUB CATEGORY",
    "SUGGESTED TYPE",
]

# KDPS controlled column → ControlledValue dimension (validated against Master Sheet).
CONTROLLED = {
    "SEASON": "season", "BRAND": "brand", "COLOR": "color", "GENDER": "gender",
    "SUB CATEGORY": "sub_category", "TYPE": "type", "ITEM": "item", "FIT": "fit",
    "SIZE": "size",
}

# Generic role → candidate source header names (normalised UPPER). First hit wins.
ALIASES: dict[str, list[str]] = {
    "BARCODE": [
        "BARCODE", "BAR CODE", "EAN", "EAN NO", "EANCODE", "EAN/UPC", "EAN CODE",
        "SUPPLIER BARCODE", "STOCK NO", "STOCK NO.", "EN CODE", "SKU NO", "BR-CODE",
        "BARCODE NO", "ADDITIONAL ITEM CODE", "STOCKNO",
    ],
    "DESIGN": [
        "STYLE", "STYLE CODE", "DESIGN", "STYLE NAME", "G ARTICLE", "ITEM NAME",
        "PRODUCT", "ITEM DESCRIPTION", "ITEM CODE",
    ],
    "BRAND_SRC": ["BRAND", "BRAND NAME", "FIRM", "OWNER SITE", "CATEGORY1", "COMPANY NAME"],
    "COLOR_SRC": ["COLOR", "COLOUR", "SHADE", "SHADE NAME", "ITEM GROUP"],
    "SIZE_SRC": ["SIZE", "SIZES", "AGE GROUP", "SIZE 1"],
    "QTY": [
        "QTY", "QUANTITY", "SALES QTY", "INVOICE QTY", "INVOICE_QUANTITY",
        "TOTAL QTY", "BILLED QUANTITY", "INVOICE QUANTITY",
    ],
    "MRP": [
        "MRP", "M.R.P", "M.R.P.", "UNIT MRP", "RETAIL PRICE", "RETAIL RATE",
        "TOTAL VALUE (MRP)", "MRP/",
    ],
    "PRATE_SRC": [
        "ITEM RATE", "INVOICE_RATE", "INVOICE RATE", "NET RATE", "RATE/UNIT",
        "COST PER UNIT", "NET UNIT COST", "DOC RATE", "RATE", "DP", "PURCHASE PRICE",
    ],
    "BASIC_SRC": [
        "ITEM BASE VALUE", "TAXABLE VALUE", "TAXABLE_AMOUNT", "BASIC AMOUNT",
        "COST", "MDP", "UNIT COST", "COST PRICE", "PURCHASE PRICE",
    ],
    "HSN": ["HSN", "HSN CODE", "HSNCODE", "HSN/SAC", "HSN_CODE"],
    "TAX_SRC": ["TAX PERCENTAGE", "GST %", "TAX_RATE", "TAX RATE", "GST RATE", "TAX"],
    "SEASON_SRC": ["SEASON", "ARTICLE SEASON", "SPSN"],
    "DATE_SRC": [
        "INVOICE DATE", "INVOICE_DATE", "VOUCHER DATE", "BILL DATE", "INV DATE", "DATE",
    ],
    "GENDER_SRC": ["GENDER", "GENDER + BODY"],
    # description used for taxonomy matching (concatenated, in order)
    "DESC_SRC": [
        "ITEM DESCRIPTION", "PRODUCT", "ITEM DESC", "DESCRIPTION", "CATEGORY",
        "CATEGORY NAME", "ITEM NAME", "CATEGORY5", "DEPARTMENT", "SECTION",
    ],
}

# Header keywords used to score / locate the header row in a messy sheet.
HEADER_KEYWORDS = {
    "barcode", "bar code", "ean", "ean no", "eancode", "ean/upc", "size", "sizes",
    "mrp", "m.r.p", "m.r.p.", "qty", "quantity", "sales qty", "hsn", "hsn code",
    "style", "rate", "color", "colour", "shade", "brand", "item", "design",
    "season", "cost", "tax", "product", "price", "retail", "stock no", "barcode",
}


PROFILES = [
    {
        "code": "ginesys_pt_email",
        "name": "Ginesys PT EMAIL (ABFRL distributor)",
        "archetype": "C",
        "match": {
            "sheet_contains": "PT EMAIL",
            "header_has": ["CATEGORY1", "CATEGORY2", "CATEGORY3", "CATEGORY4"],
        },
        "overrides": {
            "BARCODE": "BARCODE",
            "DESIGN": "CATEGORY2",
            "BRAND_SRC": "CATEGORY1",
            "COLOR_SRC": "CATEGORY3",
            "SIZE_SRC": "CATEGORY4",
            "QTY": "INVOICE_QUANTITY",
            "MRP": "MRP",
            "PRATE_SRC": "INVOICE_RATE",
            "TAX_SRC": "TAX_RATE",
            "HSN": "HSN CODE",
            "DATE_SRC": "INVOICE_DATE",
            "DESC_SRC": ["CATEGORY5", "DEPARTMENT", "SECTION", "DIVISION", "CATEGORY2"],
        },
        "flags": {"basic_from_taxable_per_unit": True},  # BASIC = TAXABLE_AMOUNT / QTY
    },
    {
        "code": "ginesys_billwise",
        "name": "Ginesys PT (bill-no-wise variant)",
        "archetype": "C",
        "match": {
            "sheet_contains": "PT FILE",
            "header_has": ["INVOICE_RATE", "INVOICE_QUANTITY", "RSP", "DEPARTMENT"],
        },
        "overrides": {
            "BARCODE": "BARCODE",
            "DESIGN": "STYLE",
            "SIZE_SRC": "SIZE",
            "QTY": "INVOICE_QUANTITY",
            "MRP": "MRP",
            "PRATE_SRC": "INVOICE_RATE",
            "HSN": "HSN_CODE",
            "DATE_SRC": "INVOICE_DATE",
            "DESC_SRC": ["DEPARTMENT", "SECTION", "STYLE"],
        },
    },
    {
        "code": "tally_voucher",
        "name": "Tally / Vistaar sales voucher",
        "archetype": "B",
        "match": {
            "header_has": ["STOCK NO", "PRODUCT", "BRAND", "STYLE", "SHADE", "SALES QTY"],
        },
        "overrides": {
            "BARCODE": "STOCK NO",
            "DESIGN": "STYLE",
            "BRAND_SRC": "BRAND",
            "COLOR_SRC": "SHADE",
            "SIZE_SRC": "SIZE",
            "QTY": "SALES QTY",
            "MRP": "RETAIL PRICE",
            "PRATE_SRC": "ITEM RATE",
            "BASIC_SRC": "ITEM BASE VALUE",
            "DATE_SRC": "VOUCHER DATE",
            "DESC_SRC": ["PRODUCT", "ITEM DESCRIPTION"],
        },
    },
]

GENERIC_PROFILE = {
    "code": "generic",
    "name": "Generic (header-name auto-map)",
    "archetype": "A",
    "match": {},
    "overrides": {},
    "flags": {},
}

# Filename keyword → profile code (fast path before fingerprinting).
FILENAME_HINTS = {
    "BEEVEE": "ginesys_pt_email",
    "MUFTI": "ginesys_pt_email",
    "GO COLOURS": "ginesys_pt_email",
    "GO COLORS": "ginesys_pt_email",
    "HYPHEN": "ginesys_billwise",
}
