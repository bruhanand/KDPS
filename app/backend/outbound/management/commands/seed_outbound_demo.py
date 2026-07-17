"""Seed on-hand stock for outbound demo / testing.

Uses the REAL inbound pipeline (Booking → GRN → PtFile → post_pt_inward) so that
stock-ledger, stock-on-hand, GL, vendor-bills, and SKU identity all come through
the same code path a live user would follow.  The result is observable and verifiable
through the API: ``/api/stockledger/on-hand``, ``/api/finledger/health``.

Seeded data
-----------
1. **Owned @ DEO** (Jharkhand):   2 Peter England SKUs × 15 qty each
2. **Owned @ BANKA** (Bihar):     2 Blackberrys SKUs × 15 qty each
3. **SOR/consignment @ DEO**:     2 Louis Philippe SKUs × 15 qty each

Idempotent: checks for an existing PtFile with ``original_filename`` matching the
seed's sentinel name.  Safe to run multiple times.

Usage::

    python manage.py seed_outbound_demo
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from core.documents import VoucherSeries
from inbound.models import Grn, GrnLine
from masters.models import Brand, Season, Store
from ptmapper.models import PtFile, PtRow
from stockledger.posting import post_pt_inward
from vendors.models import Booking, BookingLine, Vendor


def _fy() -> str:
    d = date.today()
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


SEED_TAG = "__outbound_demo_seed__"

# ------- SKU catalogue ---------
OWNED_DEO_SKUS = [
    {
        "BARCODE": "PE-FRM-WHT-40",
        "DESIGN": "Formal Shirt",
        "SIZE": "40",
        "COLOR": "White",
        "BRAND": "Peter England",
        "SEASON": "Spring/Summer 2026",
        "ITEM": "Shirt",
        "HSN": "6205",
        "P RATE": "850.00",
        "BASIC": "850.00",
        "MRP": "1799.00",
        "NAG": 15,
    },
    {
        "BARCODE": "PE-CHK-BLU-42",
        "DESIGN": "Check Casual Shirt",
        "SIZE": "42",
        "COLOR": "Blue",
        "BRAND": "Peter England",
        "SEASON": "Spring/Summer 2026",
        "ITEM": "Shirt",
        "HSN": "6205",
        "P RATE": "780.00",
        "BASIC": "780.00",
        "MRP": "1599.00",
        "NAG": 15,
    },
]

OWNED_BANKA_SKUS = [
    {
        "BARCODE": "BB-BLAZ-NVY-40",
        "DESIGN": "Slim Blazer",
        "SIZE": "40",
        "COLOR": "Navy",
        "BRAND": "Blackberrys",
        "SEASON": "Spring/Summer 2026",
        "ITEM": "Blazer",
        "HSN": "6203",
        "P RATE": "2400.00",
        "BASIC": "2400.00",
        "MRP": "5999.00",
        "NAG": 15,
    },
    {
        "BARCODE": "BB-TROU-GRY-34",
        "DESIGN": "Formal Trouser",
        "SIZE": "34",
        "COLOR": "Grey",
        "BRAND": "Blackberrys",
        "SEASON": "Spring/Summer 2026",
        "ITEM": "Trouser",
        "HSN": "6203",
        "P RATE": "1100.00",
        "BASIC": "1100.00",
        "MRP": "2999.00",
        "NAG": 15,
    },
]

SOR_DEO_SKUS = [
    {
        "BARCODE": "LP-POLO-BLK-L",
        "DESIGN": "Classic Polo",
        "SIZE": "L",
        "COLOR": "Black",
        "BRAND": "Louis Philippe",
        "SEASON": "Spring/Summer 2026",
        "ITEM": "T-Shirt",
        "HSN": "6109",
        "P RATE": "1400.00",
        "BASIC": "1400.00",
        "MRP": "3499.00",
        "NAG": 15,
    },
    {
        "BARCODE": "LP-SLIM-WHT-38",
        "DESIGN": "Slim Fit Shirt",
        "SIZE": "38",
        "COLOR": "White",
        "BRAND": "Louis Philippe",
        "SEASON": "Spring/Summer 2026",
        "ITEM": "Shirt",
        "HSN": "6205",
        "P RATE": "1800.00",
        "BASIC": "1800.00",
        "MRP": "4299.00",
        "NAG": 15,
    },
]


def _already_seeded() -> bool:
    return PtFile.objects.filter(original_filename__startswith=SEED_TAG).exists()


def _allocate_booking_number(season: Season) -> str:
    fy = _fy()
    scope = season.code[:16]
    VoucherSeries.objects.get_or_create(fy=fy, store_code=scope, doc_type="BK")
    _, number = VoucherSeries.allocate(fy=fy, store_code=scope, doc_type="BK")
    return number


def _get_or_create_booking(
    vendor: Vendor,
    brand: Brand,
    season: Season,
    dest_store: Store,
    skus: list[dict],
    tag: str,
    user: User,
) -> Booking:
    """Create a booking with lines matching the SKU catalogue.  Reuse if the
    seed sentinel is in ``notes``."""
    existing = Booking.objects.filter(notes__contains=tag).first()
    if existing:
        return existing

    number = _allocate_booking_number(season)
    bk = Booking.objects.create(
        number=number,
        vendor=vendor,
        brand=brand,
        season=season,
        destination_store=dest_store,
        status=Booking.Status.BOOKED,
        ownership=brand.ownership,
        return_terms=brand.return_terms,
        notes=tag,
        created_by=user,
    )
    for sku in skus:
        BookingLine.objects.create(
            booking=bk,
            store=dest_store,
            style_code=sku["DESIGN"],
            size=sku["SIZE"],
            booked_qty=sku["NAG"],
        )
    return bk


def _create_grn(
    booking: Booking,
    store: Store,
    user: User,
    tag: str,
    skus: list[dict],
) -> Grn:
    """Create & post a GRN for the seed booking."""
    fy = _fy()
    VoucherSeries.objects.get_or_create(fy=fy, store_code=store.code, doc_type="GRN")

    grn = Grn.objects.create(
        booking=booking,
        vendor=booking.vendor,
        store=store,
        received_at=Grn.ReceivedAt.STORE,
        kind=Grn.Kind.BRANDED,
        is_direct=False,
        invoice_number=f"SEED-INV-{tag}",
        notes=f"Seed demo stock ({tag})",
        received_by=user,
    )
    for sku in skus:
        bl = booking.lines.filter(style_code=sku["DESIGN"], size=sku["SIZE"]).first()
        GrnLine.objects.create(
            grn=grn,
            booking_line=bl,
            style_code=sku["DESIGN"],
            size=sku["SIZE"],
            color=sku.get("COLOR", ""),
            barcode=sku["BARCODE"],
            received_qty=sku["NAG"],
        )
        if bl:
            bl.received_qty += sku["NAG"]
            bl.save(update_fields=["received_qty", "updated_at"])
    grn.post()
    booking.recompute_status()
    return grn


def _create_and_post_pt(
    grn: Grn,
    booking: Booking,
    store: Store,
    user: User,
    tag: str,
    skus: list[dict],
) -> dict:
    """Create a PtFile with mapped rows, advance to 'sent', then post via the
    real posting engine."""
    fy = _fy()
    VoucherSeries.objects.get_or_create(fy=fy, store_code=store.code, doc_type="PT")

    pt = PtFile.objects.create(
        grn=grn,
        source=PtFile.Source.BRAND_FILE,
        original_filename=f"{SEED_TAG}{tag}",
        brand_guess=booking.brand.name,
        profile_code="seed",
        status=PtFile.Status.READY,
        draft_stage=PtFile.DraftStage.SENT,
        row_count=len(skus),
        created_by=user,
    )
    for i, sku in enumerate(skus, start=1):
        PtRow.objects.create(
            pt_file=pt,
            line_no=i,
            data=sku,
        )

    result = post_pt_inward(pt, user, booking=booking)
    return result


class Command(BaseCommand):
    help = "Seed on-hand stock via the real inbound pipeline for outbound demo testing."

    @transaction.atomic
    def handle(self, *args, **options):
        if _already_seeded():
            self.stdout.write(
                self.style.WARNING(
                    "Outbound demo stock already seeded (sentinel PtFiles found). Skipping."
                )
            )
            return

        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.first()
        self.stdout.write(f"Seeding as user: {user.username}")

        # Ensure VoucherSeries exist for all outbound doc types at all stores.
        fy = _fy()
        for store in Store.objects.all():
            for dt in ("STO", "RTV", "ADJ", "WRO", "VFL"):
                VoucherSeries.objects.get_or_create(fy=fy, store_code=store.code, doc_type=dt)

        deo = Store.objects.get(code="DEO")
        banka = Store.objects.get(code="BANKA")
        season = Season.objects.get(name="Spring/Summer 2026")

        # ---------- 1. Owned @ DEO (Peter England via ABFRL) ----------
        pe_brand = Brand.objects.get(name="Peter England")
        abfrl = Vendor.objects.get(code="abfrl")

        bk_pe_deo = _get_or_create_booking(
            abfrl, pe_brand, season, deo, OWNED_DEO_SKUS, "seed-pe-deo", user
        )
        grn_pe_deo = _create_grn(bk_pe_deo, deo, user, "pe-deo", OWNED_DEO_SKUS)
        res = _create_and_post_pt(grn_pe_deo, bk_pe_deo, deo, user, "pe-deo", OWNED_DEO_SKUS)
        self.stdout.write(
            self.style.SUCCESS(
                f"  Owned @ DEO: {res['doc_number']} — {res['entries']} entries, "
                f"model={res['commercial_model']}, value=₹{res['stock_value_paise'] / 100:.2f}"
            )
        )

        # ---------- 2. Owned @ BANKA (Blackberrys via Blackberrys Menswear) ----------
        bb_brand = Brand.objects.get(name="Blackberrys")
        bb_vendor = Vendor.objects.get(code="blackberrys")

        bk_bb_banka = _get_or_create_booking(
            bb_vendor, bb_brand, season, banka, OWNED_BANKA_SKUS, "seed-bb-banka", user
        )
        grn_bb_banka = _create_grn(bk_bb_banka, banka, user, "bb-banka", OWNED_BANKA_SKUS)
        res = _create_and_post_pt(
            grn_bb_banka, bk_bb_banka, banka, user, "bb-banka", OWNED_BANKA_SKUS
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  Owned @ BANKA: {res['doc_number']} — {res['entries']} entries, "
                f"model={res['commercial_model']}, value=₹{res['stock_value_paise'] / 100:.2f}"
            )
        )

        # ---------- 3. SOR/consignment @ DEO (Louis Philippe via ABFRL) ----------
        lp_brand = Brand.objects.get(name="Louis Philippe")

        bk_lp_deo = _get_or_create_booking(
            abfrl, lp_brand, season, deo, SOR_DEO_SKUS, "seed-lp-deo", user
        )
        grn_lp_deo = _create_grn(bk_lp_deo, deo, user, "lp-deo", SOR_DEO_SKUS)
        res = _create_and_post_pt(grn_lp_deo, bk_lp_deo, deo, user, "lp-deo", SOR_DEO_SKUS)
        self.stdout.write(
            self.style.SUCCESS(
                f"  SOR @ DEO: {res['doc_number']} — {res['entries']} entries, "
                f"model={res['commercial_model']}, value=₹{res['stock_value_paise'] / 100:.2f}"
            )
        )

        self.stdout.write(self.style.SUCCESS("\nOutbound demo stock seeded successfully."))
        self.stdout.write("  Verify: GET /api/stockledger/on-hand")
        self.stdout.write("  Verify: GET /api/finledger/health")
