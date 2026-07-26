"""Whole-system demo data seed: every module, every store, real code paths.

Builds on ``seed_foundation`` (roles/masters/users) and complements
``seed_outbound_demo`` (which stocks DEO + BANKA). This command:

1. Cleans test junk left behind by API test runs (ZZTEST* stores, ZZS*/ZZB*
   seasons/brands, orphan GSTINs, test.auto.* users and their roles).
2. Receives stock at ALL six locations through the real inbound pipeline
   (Booking → GRN → PtFile → ``post_pt_inward``) across 8 brands, both
   commercial models (owned + SOR), two seasons, plus one direct (booking-less)
   receipt and one partially received booking and one still-open order.
3. Seeds the outbound document zoo in every lifecycle state: transfers
   (received / shortfall + gap closure / in transit / cross-state / with
   damaged arrivals), damage flags (confirmed and pending), RTVs (defective,
   seasonal, draft), stock adjustments (auto-cleared, approved, pending),
   a V-flip, and stocktakes (applied variance + one mid-count).
4. Seeds money: vendor payments and cash/bank/UPI movements through
   ``finledger.posting`` so the GL stays balanced.

Everything goes through the same service functions the API uses — no raw
ledger writes — so ledgers, projections and the trial balance stay honest.

Idempotent via a sentinel on the seeded bookings' notes. Safe to run on a dev
or preview database; do NOT run against live books.

Usage::

    python manage.py seed_demo_data
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role, User
from approvals.models import ApprovalStatus
from approvals.services import approval_for, decide
from core.documents import VoucherSeries
from finledger.posting import post_cash_movement, post_vendor_payment, rupees_to_paise
from inbound.models import Grn, GrnLine
from masters.models import Brand, Gstin, Season, Store
from outbound.counting import (
    apply_variance,
    open_session,
    open_stocktake,
    record_scans,
    submit_session,
)
from outbound.maker_checker import request_document_approval
from outbound.models import (
    AdjustmentReason,
    GapReason,
    LogisticsRoute,
    ReturnToVendor,
    ReturnToVendorLine,
    ReturnType,
    StockAdjustment,
    StockAdjustmentLine,
    StoreTransfer,
    TransferReason,
    TransferType,
    TransportMode,
    VFlip,
    VFlipLine,
)
from outbound.posting import (
    mark_damaged,
    post_adjustment,
    post_gap_closure,
    post_rtv,
    post_transfer_dispatch,
    post_transfer_receipt,
    post_vflip,
    raise_gap_closure,
    resolve_line_identity,
)
from ptmapper.models import PtFile, PtRow
from stockledger.models import StockOnHand
from stockledger.posting import post_pt_inward
from vendors.models import Booking, BookingLine, Vendor

SEED_TAG = "demo-wave2"
DOC_TYPES = ("GRN", "PT", "STO", "DMG", "GAP", "RTV", "ADJ", "WRO", "VFL")
REAL_GSTINS = {"10AAACK1234M1Z5", "20AAACK1234M1Z3"}


def _fy() -> str:
    d = date.today()
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _sku(
    barcode: str,
    design: str,
    size: str,
    color: str,
    brand: str,
    season: str,
    item: str,
    hsn: str,
    cost: float,
    mrp: float,
    qty: int,
) -> dict[str, Any]:
    return {
        "BARCODE": barcode,
        "DESIGN": design,
        "SIZE": size,
        "COLOR": color,
        "BRAND": brand,
        "SEASON": season,
        "ITEM": item,
        "HSN": hsn,
        "P RATE": f"{cost:.2f}",
        "BASIC": f"{cost:.2f}",
        "MRP": f"{mrp:.2f}",
        "NAG": qty,
    }


SS26 = "Spring/Summer 2026"
AW25 = "Autumn/Winter 2025"

# One entry per goods receipt: booking → GRN → PT → posted stock.
# "partial" receives less than booked; "direct" skips the booking entirely.
RECEIPTS: list[dict[str, Any]] = [
    {
        "tag": "lp-wh",
        "vendor": "abfrl",
        "brand": "Louis Philippe",
        "season": "SS26",
        "store": "RAN-WH",
        "skus": [
            _sku(
                "LP-OXF-BLU-40",
                "Oxford Shirt",
                "40",
                "Blue",
                "Louis Philippe",
                SS26,
                "Shirt",
                "6205",
                1650,
                3999,
                30,
            ),
            _sku(
                "LP-CHN-KHA-34",
                "Slim Chino",
                "34",
                "Khaki",
                "Louis Philippe",
                SS26,
                "Trouser",
                "6203",
                1750,
                4299,
                24,
            ),
            _sku(
                "LP-TEE-NVY-M",
                "Crew Tee",
                "M",
                "Navy",
                "Louis Philippe",
                SS26,
                "T-Shirt",
                "6109",
                900,
                2199,
                36,
            ),
        ],
    },
    {
        "tag": "pe-wh",
        "vendor": "abfrl",
        "brand": "Peter England",
        "season": "SS26",
        "store": "RAN-WH",
        "skus": [
            _sku(
                "PE-PLO-GRN-L",
                "Pique Polo",
                "L",
                "Green",
                "Peter England",
                SS26,
                "T-Shirt",
                "6109",
                520,
                1099,
                30,
            ),
            _sku(
                "PE-DNM-IND-32",
                "Slim Jeans",
                "32",
                "Indigo",
                "Peter England",
                SS26,
                "Jeans",
                "6203",
                980,
                2299,
                24,
            ),
            _sku(
                "PE-FRM-LAV-42",
                "Formal Shirt",
                "42",
                "Lavender",
                "Peter England",
                SS26,
                "Shirt",
                "6205",
                760,
                1699,
                30,
            ),
        ],
    },
    {
        "tag": "bb-wh",
        "vendor": "blackberrys",
        "brand": "Blackberrys",
        "season": "SS26",
        "store": "RAN-WH",
        "skus": [
            _sku(
                "BB-SUIT-CHR-42",
                "Two-Piece Suit",
                "42",
                "Charcoal",
                "Blackberrys",
                SS26,
                "Suit",
                "6203",
                5200,
                12999,
                12,
            ),
            _sku(
                "BB-SHRT-WHT-40",
                "Formal Shirt",
                "40",
                "White",
                "Blackberrys",
                SS26,
                "Shirt",
                "6205",
                950,
                2499,
                24,
            ),
        ],
    },
    {
        "tag": "mf-deo",
        "vendor": "credo",
        "brand": "Mufti",
        "season": "SS26",
        "store": "DEO",
        "skus": [
            _sku(
                "MF-JEAN-BLK-32",
                "Slim Jeans",
                "32",
                "Black",
                "Mufti",
                SS26,
                "Jeans",
                "6203",
                1150,
                2799,
                16,
            ),
            _sku(
                "MF-TEE-OLV-L",
                "Graphic Tee",
                "L",
                "Olive",
                "Mufti",
                SS26,
                "T-Shirt",
                "6109",
                480,
                1199,
                20,
            ),
        ],
    },
    {
        "tag": "vh-deo",
        "vendor": "abfrl",
        "brand": "Van Heusen",
        "season": "SS26",
        "store": "DEO",
        "skus": [
            _sku(
                "VH-BLZR-GRY-40",
                "Formal Blazer",
                "40",
                "Grey",
                "Van Heusen",
                SS26,
                "Blazer",
                "6203",
                2800,
                6999,
                8,
            ),
            _sku(
                "VH-SHRT-PNK-39",
                "Formal Shirt",
                "39",
                "Pink",
                "Van Heusen",
                SS26,
                "Shirt",
                "6205",
                820,
                1999,
                16,
            ),
        ],
    },
    {
        "tag": "as-bkr",
        "vendor": "abfrl",
        "brand": "Allen Solly",
        "season": "SS26",
        "store": "BKR",
        "skus": [
            _sku(
                "AS-POLO-YLW-M",
                "Solly Polo",
                "M",
                "Yellow",
                "Allen Solly",
                SS26,
                "T-Shirt",
                "6109",
                640,
                1499,
                18,
            ),
            _sku(
                "AS-CHNO-BEI-34",
                "Casual Chino",
                "34",
                "Beige",
                "Allen Solly",
                SS26,
                "Trouser",
                "6203",
                1050,
                2599,
                14,
            ),
        ],
    },
    {
        "tag": "kl-bkr",
        "vendor": "kewalkiran",
        "brand": "Killer",
        "season": "AW25",
        "store": "BKR",
        "skus": [
            _sku(
                "KL-JEAN-DKB-30",
                "Torn Jeans",
                "30",
                "Dark Blue",
                "Killer",
                AW25,
                "Jeans",
                "6203",
                1180,
                2899,
                16,
            ),
            _sku(
                "KL-JKT-BLK-L",
                "Denim Jacket",
                "L",
                "Black",
                "Killer",
                AW25,
                "Jacket",
                "6201",
                1500,
                3699,
                10,
            ),
        ],
    },
    {
        "tag": "usp-hzb",
        "vendor": "arvind",
        "brand": "U.S. Polo Assn.",
        "season": "SS26",
        "store": "HZB",
        "skus": [
            _sku(
                "USP-TEE-WHT-L",
                "Logo Tee",
                "L",
                "White",
                "U.S. Polo Assn.",
                SS26,
                "T-Shirt",
                "6109",
                520,
                1299,
                20,
            ),
            _sku(
                "USP-SHRT-CHK-42",
                "Check Shirt",
                "42",
                "Red Check",
                "U.S. Polo Assn.",
                SS26,
                "Shirt",
                "6205",
                900,
                2199,
                14,
            ),
        ],
    },
    {
        "tag": "spy-hzb",
        "vendor": "arvind",
        "brand": "Spykar",
        "season": "AW25",
        "store": "HZB",
        "direct": True,
        "skus": [
            _sku(
                "SPY-JEAN-GRY-32",
                "Skinny Jeans",
                "32",
                "Grey",
                "Spykar",
                AW25,
                "Jeans",
                "6203",
                1100,
                2699,
                15,
            ),
            _sku(
                "SPY-TEE-RED-M",
                "Round Neck Tee",
                "M",
                "Red",
                "Spykar",
                AW25,
                "T-Shirt",
                "6109",
                380,
                999,
                18,
            ),
        ],
    },
    {
        "tag": "jky-dum",
        "vendor": "page",
        "brand": "Jockey",
        "season": "SS26",
        "store": "DUM",
        "partial": {"JKY-TRK-NVY-L": 12},
        "skus": [
            _sku(
                "JKY-TRK-NVY-L",
                "Track Pant",
                "L",
                "Navy",
                "Jockey",
                SS26,
                "Trouser",
                "6104",
                520,
                1299,
                24,
            ),
            _sku(
                "JKY-TEE-GRY-M",
                "Essential Tee",
                "M",
                "Grey",
                "Jockey",
                SS26,
                "T-Shirt",
                "6109",
                300,
                799,
                24,
            ),
        ],
    },
    {
        "tag": "pe-dum",
        "vendor": "abfrl",
        "brand": "Peter England",
        "season": "SS26",
        "store": "DUM",
        "skus": [
            _sku(
                "PE-SHRT-WHT-39",
                "Formal Shirt",
                "39",
                "White",
                "Peter England",
                SS26,
                "Shirt",
                "6205",
                720,
                1599,
                14,
            ),
            _sku(
                "PE-TRSR-GRY-34",
                "Formal Trouser",
                "34",
                "Grey",
                "Peter England",
                SS26,
                "Trouser",
                "6203",
                1050,
                2499,
                12,
            ),
        ],
    },
    {
        "tag": "vh-banka",
        "vendor": "abfrl",
        "brand": "Van Heusen",
        "season": "SS26",
        "store": "BANKA",
        "skus": [
            _sku(
                "VH-TRSR-NVY-34",
                "Formal Trouser",
                "34",
                "Navy",
                "Van Heusen",
                SS26,
                "Trouser",
                "6203",
                1150,
                2799,
                12,
            ),
            _sku(
                "VH-SHRT-WHT-42",
                "Formal Shirt",
                "42",
                "White",
                "Van Heusen",
                SS26,
                "Shirt",
                "6205",
                820,
                1999,
                16,
            ),
        ],
    },
    {
        "tag": "mf-banka",
        "vendor": "credo",
        "brand": "Mufti",
        "season": "AW25",
        "store": "BANKA",
        "skus": [
            _sku(
                "MF-SHKT-DNM-40",
                "Denim Shacket",
                "40",
                "Indigo",
                "Mufti",
                AW25,
                "Jacket",
                "6201",
                1350,
                3299,
                10,
            ),
            _sku(
                "MF-CRGO-OLV-34",
                "Cargo Pant",
                "34",
                "Olive",
                "Mufti",
                AW25,
                "Trouser",
                "6203",
                1100,
                2699,
                14,
            ),
        ],
    },
]


class Command(BaseCommand):
    help = "Seed rich demo data across every module and store (idempotent)."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if Booking.objects.filter(notes__contains=SEED_TAG).exists():
            self.stdout.write(
                self.style.WARNING("Demo wave already seeded (sentinel bookings found). Skipping.")
            )
            return

        call_command("seed_foundation")
        self._clean_test_junk()
        self._ensure_series()

        self.users = {
            u.username: u
            for u in User.objects.filter(
                username__in=[
                    "superadmin",
                    "owner",
                    "ops1",
                    "wh.patna",
                    "wh.ranchi",
                    "deo.manager",
                    "deo.cashier",
                    "bkr.manager",
                    "bkr.cashier",
                    "hzb.manager",
                    "dum.manager",
                    "banka.manager",
                ]
            )
        }
        self.stores = {s.code: s for s in Store.objects.all()}
        self.vendors = {v.code: v for v in Vendor.objects.all()}
        self.brands = {b.name: b for b in Brand.objects.all()}
        self.seasons = {s.code: s for s in Season.objects.all()}

        self._seed_inbound()
        self._seed_open_and_booked_orders()
        self._seed_transfers()
        self._seed_damage()
        self._seed_rtvs()
        self._seed_adjustments()
        self._seed_vflip()
        self._seed_stocktakes()
        self._seed_money()

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded across all modules."))
        self.stdout.write("  Verify: GET /api/stockledger/on-hand, /api/finledger/health")

    # ------------------------------------------------------------------
    # 0. cleanup + series
    # ------------------------------------------------------------------
    def _clean_test_junk(self) -> None:
        """Remove masters/users left behind by API test runs against the dev DB.

        Only rows matching the test fixtures' unmistakable naming patterns are
        touched, and PROTECT FKs guarantee anything referenced survives.
        """
        n_users, _ = User.objects.filter(username__startswith="test.auto.").delete()
        n_roles, _ = Role.objects.filter(code__startswith="test_auto_role_").delete()
        n_stores, _ = Store.objects.filter(code__startswith="ZZTEST").delete()
        n_seasons, _ = Season.objects.filter(code__startswith="ZZS").delete()
        n_brands, _ = Brand.objects.filter(code__startswith="ZZB").delete()
        n_gstins, _ = (
            Gstin.objects.exclude(gstin__in=REAL_GSTINS).filter(stores__isnull=True).delete()
        )
        cleaned = n_users + n_roles + n_stores + n_seasons + n_brands + n_gstins
        if cleaned:
            self.stdout.write(
                f"Cleaned test junk: {n_users} users, {n_roles} roles, {n_stores} stores, "
                f"{n_seasons} seasons, {n_brands} brands, {n_gstins} GSTINs"
            )

    def _ensure_series(self) -> None:
        fy = _fy()
        for store in Store.objects.all():
            for dt in DOC_TYPES:
                VoucherSeries.objects.get_or_create(fy=fy, store_code=store.code, doc_type=dt)

    # ------------------------------------------------------------------
    # 1. inbound: booking → GRN → PT → posted stock
    # ------------------------------------------------------------------
    def _make_booking(
        self,
        vendor: Vendor,
        brand: Brand,
        season: Season,
        store: Store,
        skus: list[dict[str, Any]],
        tag: str,
        user: User,
    ) -> Booking:
        fy = _fy()
        scope = season.code[:16]
        VoucherSeries.objects.get_or_create(fy=fy, store_code=scope, doc_type="BK")
        _, number = VoucherSeries.allocate(fy=fy, store_code=scope, doc_type="BK")
        booking = Booking.objects.create(
            number=number,
            vendor=vendor,
            brand=brand,
            season=season,
            destination_store=store,
            status=Booking.Status.BOOKED,
            ownership=brand.ownership,
            return_terms=brand.return_terms,
            notes=f"{SEED_TAG}:{tag}",
            created_by=user,
        )
        for sku in skus:
            BookingLine.objects.create(
                booking=booking,
                store=store,
                style_code=sku["DESIGN"],
                size=sku["SIZE"],
                booked_qty=sku["NAG"],
                mrp_paise=int(round(float(sku["MRP"]) * 100)),
            )
        booking.estimated_value_paise = sum(
            line.booked_qty * (line.mrp_paise or 0) for line in booking.lines.all()
        )
        booking.save(update_fields=["estimated_value_paise"])
        return booking

    def _make_grn(
        self,
        booking: Booking | None,
        vendor: Vendor,
        store: Store,
        skus: list[dict[str, Any]],
        tag: str,
        user: User,
        received: dict[str, int],
    ) -> Grn:
        grn = Grn.objects.create(
            booking=booking,
            vendor=vendor,
            store=store,
            received_at=(
                Grn.ReceivedAt.WAREHOUSE
                if store.store_type == "warehouse"
                else Grn.ReceivedAt.STORE
            ),
            kind=Grn.Kind.BRANDED,
            is_direct=booking is None,
            invoice_number=f"DM-INV-{tag.upper()}",
            notes=f"{SEED_TAG}:{tag}",
            received_by=user,
        )
        for sku in skus:
            qty = received.get(sku["BARCODE"], sku["NAG"])
            if qty <= 0:
                continue
            bl = (
                booking.lines.filter(style_code=sku["DESIGN"], size=sku["SIZE"]).first()
                if booking
                else None
            )
            GrnLine.objects.create(
                grn=grn,
                booking_line=bl,
                style_code=sku["DESIGN"],
                size=sku["SIZE"],
                color=sku["COLOR"],
                barcode=sku["BARCODE"],
                received_qty=qty,
            )
            if bl:
                bl.received_qty += qty
                bl.save(update_fields=["received_qty", "updated_at"])
        grn.post()
        if booking:
            booking.recompute_status()
        return grn

    def _post_pt(
        self,
        grn: Grn,
        booking: Booking | None,
        brand: Brand,
        skus: list[dict[str, Any]],
        tag: str,
        user: User,
        received: dict[str, int],
    ) -> dict[str, Any]:
        rows = []
        for sku in skus:
            qty = received.get(sku["BARCODE"], sku["NAG"])
            if qty > 0:
                rows.append({**sku, "NAG": qty})
        pt = PtFile.objects.create(
            grn=grn,
            source=PtFile.Source.BRAND_FILE,
            original_filename=f"{SEED_TAG}-{tag}.xlsx",
            brand_guess=brand.name,
            profile_code="seed",
            status=PtFile.Status.READY,
            draft_stage=PtFile.DraftStage.SENT,
            row_count=len(rows),
            created_by=user,
        )
        for i, row in enumerate(rows, start=1):
            PtRow.objects.create(pt_file=pt, line_no=i, data=row)
        return post_pt_inward(pt, user, booking=booking)

    def _seed_inbound(self) -> None:
        wh_user = self.users["wh.ranchi"]
        for spec in RECEIPTS:
            vendor = self.vendors[spec["vendor"]]
            brand = self.brands[spec["brand"]]
            season = self.seasons[spec["season"]]
            store = self.stores[spec["store"]]
            skus = spec["skus"]
            received: dict[str, int] = spec.get("partial", {})
            booking = (
                None
                if spec.get("direct")
                else self._make_booking(vendor, brand, season, store, skus, spec["tag"], wh_user)
            )
            grn = self._make_grn(booking, vendor, store, skus, spec["tag"], wh_user, received)
            res = self._post_pt(grn, booking, brand, skus, spec["tag"], wh_user, received)
            self.stdout.write(
                f"  Inbound {spec['tag']}: {res['doc_number']} @ {store.code} "
                f"model={res['commercial_model']} ₹{res['stock_value_paise'] / 100:,.0f}"
            )

    def _seed_open_and_booked_orders(self) -> None:
        """One booking still awaiting goods, so the Bookings screen shows an open order."""
        self._make_booking(
            self.vendors["abfrl"],
            self.brands["Van Heusen"],
            self.seasons["SS26"],
            self.stores["DEO"],
            [
                _sku(
                    "VH-POLO-BLU-M",
                    "Luxe Polo",
                    "M",
                    "Blue",
                    "Van Heusen",
                    SS26,
                    "T-Shirt",
                    "6109",
                    750,
                    1799,
                    24,
                ),
                _sku(
                    "VH-TEE-WHT-L",
                    "Crew Tee",
                    "L",
                    "White",
                    "Van Heusen",
                    SS26,
                    "T-Shirt",
                    "6109",
                    540,
                    1299,
                    36,
                ),
            ],
            "vh-open-order",
            self.users["ops1"],
        )
        self.stdout.write("  Open order: VH booking awaiting goods @ DEO")

    # ------------------------------------------------------------------
    # 2. transfers
    # ------------------------------------------------------------------
    def _transfer(
        self,
        source: Store,
        dest: Store,
        ttype: str,
        reason: str,
        scans: dict[str, int],
        user: User,
    ) -> StoreTransfer:
        t = StoreTransfer.objects.create(
            source_store=source,
            destination_store=dest,
            transfer_type=ttype,
            reason=reason,
            transport_mode=TransportMode.OWN_VEHICLE,
            transport_ref=f"KDPS-VAN-{dest.code}",
            created_by=user,
        )
        post_transfer_dispatch(t, scans, user)
        return t

    def _seed_transfers(self) -> None:
        wh = self.stores["RAN-WH"]
        ops1 = self.users["ops1"]
        wh_user = self.users["wh.ranchi"]

        # T1: warehouse → DEO, dispatched and fully received.
        t1 = self._transfer(
            wh,
            self.stores["DEO"],
            TransferType.STORE_SPLIT,
            TransferReason.SISTER_STORE_REQUEST,
            {"LP-OXF-BLU-40": 6, "PE-PLO-GRN-L": 8},
            wh_user,
        )
        post_transfer_receipt(
            t1, {"LP-OXF-BLU-40": 6, "PE-PLO-GRN-L": 8}, self.users["deo.manager"]
        )
        self.stdout.write(f"  Transfer {t1.doc_number}: RAN-WH → DEO, received in full")

        # T2: warehouse → BKR, received short → gap closed as lost in transit.
        t2 = self._transfer(
            wh,
            self.stores["BKR"],
            TransferType.STORE_SPLIT,
            TransferReason.SLOW_MOVER,
            {"BB-SUIT-CHR-42": 5, "BB-SHRT-WHT-40": 6},
            wh_user,
        )
        post_transfer_receipt(
            t2,
            {"BB-SUIT-CHR-42": 3, "BB-SHRT-WHT-40": 6},
            self.users["bkr.manager"],
            notes="Carton arrived retaped; two suits missing.",
        )
        closure = raise_gap_closure(
            t2,
            reason=GapReason.LOST_IN_TRANSIT,
            note="Transporter confirms one bundle lost between Ranchi and Bokaro.",
            user=ops1,
        )
        approval = approval_for(closure)
        if approval is not None and approval.status == ApprovalStatus.PENDING:
            decide(approval, actor=self.users["owner"], action="approve")
        post_gap_closure(closure, user=ops1)
        self.stdout.write(f"  Transfer {t2.doc_number}: RAN-WH → BKR, shortfall + gap closed")

        # T3: warehouse → HZB, still on the truck.
        t3 = self._transfer(
            wh,
            self.stores["HZB"],
            TransferType.STORE_SPLIT,
            TransferReason.SEASONAL_SWAP,
            {"PE-DNM-IND-32": 6, "LP-TEE-NVY-M": 6},
            wh_user,
        )
        self.stdout.write(f"  Transfer {t3.doc_number}: RAN-WH → HZB, in transit")

        # T4: DEO → DUM inter-store; one piece arrives damaged (store flags it).
        t4 = self._transfer(
            self.stores["DEO"],
            self.stores["DUM"],
            TransferType.INTER_STORE,
            TransferReason.CUSTOMER_WAITING,
            {"MF-TEE-OLV-L": 4},
            self.users["deo.manager"],
        )
        post_transfer_receipt(
            t4,
            {"MF-TEE-OLV-L": 3},
            self.users["dum.manager"],
            damaged={"MF-TEE-OLV-L": 1},
            notes="One tee crushed under the strap.",
        )
        self.stdout.write(f"  Transfer {t4.doc_number}: DEO → DUM, 1 damaged arrival flagged")

        # T5: warehouse (Jharkhand) → BANKA (Bihar) — a cross-state, IGST-relevant move.
        t5 = self._transfer(
            wh,
            self.stores["BANKA"],
            TransferType.STORE_SPLIT,
            TransferReason.SISTER_STORE_REQUEST,
            {"LP-CHN-KHA-34": 5, "PE-FRM-LAV-42": 6},
            wh_user,
        )
        post_transfer_receipt(
            t5, {"LP-CHN-KHA-34": 5, "PE-FRM-LAV-42": 6}, self.users["banka.manager"]
        )
        state = "cross-state" if t5.is_cross_state else "intra-state"
        self.stdout.write(f"  Transfer {t5.doc_number}: RAN-WH → BANKA, received ({state})")

    # ------------------------------------------------------------------
    # 3. damage
    # ------------------------------------------------------------------
    def _seed_damage(self) -> None:
        d1 = mark_damaged(
            self.stores["DEO"],
            {"MF-JEAN-BLK-32": 1},
            user=self.users["wh.patna"],
            note="Water stain on the left leg — unsellable.",
        )
        self.stdout.write(f"  Damage {d1.doc_number or '(draft)'} @ DEO: confirmed by warehouse")
        d2 = mark_damaged(
            self.stores["BKR"],
            {"KL-JKT-BLK-L": 1},
            user=self.users["bkr.cashier"],
            note="Zip runner snapped during trial.",
        )
        state = "posted" if d2.doc_number else "pending confirmation"
        self.stdout.write(f"  Damage flag @ BKR: {state}")

    # ------------------------------------------------------------------
    # 4. RTVs
    # ------------------------------------------------------------------
    def _rtv_line(
        self, rtv: ReturnToVendor, store: Store, sku: str, qty: int, season: str = ""
    ) -> None:
        identity = resolve_line_identity(store.id, sku, season)
        ReturnToVendorLine.objects.create(rtv=rtv, sku_code=sku, qty=qty, **identity)

    def _seed_rtvs(self) -> None:
        ops1 = self.users["ops1"]
        deo = self.stores["DEO"]
        rtv1 = ReturnToVendor.objects.create(
            store=deo,
            vendor=self.vendors["abfrl"],
            brand=self.brands["Peter England"],
            return_type=ReturnType.DEFECTIVE,
            logistics_route=LogisticsRoute.STORE_PICKUP,
            notes=f"{SEED_TAG}: stitching defects reported at billing",
            created_by=ops1,
        )
        self._rtv_line(rtv1, deo, "PE-CHK-BLU-42", 2)
        post_rtv(rtv1, ops1)
        self.stdout.write(f"  RTV {rtv1.doc_number} @ DEO: defective, posted")

        banka = self.stores["BANKA"]
        rtv2 = ReturnToVendor.objects.create(
            store=banka,
            vendor=self.vendors["blackberrys"],
            brand=self.brands["Blackberrys"],
            return_type=ReturnType.SEASONAL,
            logistics_route=LogisticsRoute.WAREHOUSE_CONSOLIDATION,
            season=SS26,
            return_window_date=date.today() + timedelta(days=30),
            notes=f"{SEED_TAG}: season-end return within window",
            created_by=ops1,
        )
        self._rtv_line(rtv2, banka, "BB-TROU-GRY-34", 3)
        post_rtv(rtv2, ops1)
        self.stdout.write(f"  RTV {rtv2.doc_number} @ BANKA: seasonal, posted")

        hzb = self.stores["HZB"]
        rtv3 = ReturnToVendor.objects.create(
            store=hzb,
            vendor=self.vendors["arvind"],
            brand=self.brands["Spykar"],
            return_type=ReturnType.DEFECTIVE,
            notes=f"{SEED_TAG}: draft awaiting pickup confirmation",
            created_by=ops1,
        )
        self._rtv_line(rtv3, hzb, "SPY-JEAN-GRY-32", 2)
        self.stdout.write("  RTV draft @ HZB: unposted")

    # ------------------------------------------------------------------
    # 5. adjustments
    # ------------------------------------------------------------------
    def _adjustment(
        self, store: Store, reason: str, deltas: dict[str, int], maker: User, note: str
    ) -> StockAdjustment:
        adj = StockAdjustment.objects.create(
            store=store, reason=reason, notes=note, created_by=maker
        )
        for sku, delta in deltas.items():
            identity = resolve_line_identity(store.id, sku)
            on_hand = StockOnHand.objects.filter(store=store, sku_code=sku).first()
            book = on_hand.net_qty if on_hand else 0
            StockAdjustmentLine.objects.create(
                adjustment=adj,
                sku_code=sku,
                book_qty=book,
                counted_qty=book + delta,
                adj_qty=delta,
                **identity,
            )
        request_document_approval(adj, requested_by=maker)
        return adj

    def _seed_adjustments(self) -> None:
        ops1 = self.users["ops1"]

        # Small surplus at BKR — inside tolerance, clears itself and posts.
        adj1 = self._adjustment(
            self.stores["BKR"],
            AdjustmentReason.SURPLUS_FOUND,
            {"AS-POLO-YLW-M": 2},
            ops1,
            "Two polos found in the trial-room return bin.",
        )
        approval = approval_for(adj1)
        if approval is not None and approval.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.NOT_REQUIRED,
        ):
            post_adjustment(adj1, user=ops1)
            self.stdout.write(f"  Adjustment {adj1.doc_number} @ BKR: surplus, auto-cleared")

        # Big shrinkage at DEO — left sitting in the approvals inbox.
        self._adjustment(
            self.stores["DEO"],
            AdjustmentReason.SHRINKAGE,
            {"VH-BLZR-GRY-40": -2},
            ops1,
            "Two blazers unaccounted for after the weekend rush.",
        )
        self.stdout.write("  Adjustment @ DEO: shrinkage, awaiting approval")

        # Shrinkage at DUM — approved by the store manager, then posted.
        adj3 = self._adjustment(
            self.stores["DUM"],
            AdjustmentReason.SHRINKAGE,
            {"PE-SHRT-WHT-39": -3},
            ops1,
            "Shortfall confirmed against the rack count.",
        )
        approval = approval_for(adj3)
        if approval is not None and approval.status == ApprovalStatus.PENDING:
            decide(approval, actor=self.users["dum.manager"], action="approve")
        post_adjustment(adj3, user=ops1)
        self.stdout.write(f"  Adjustment {adj3.doc_number} @ DUM: approved and posted")

    # ------------------------------------------------------------------
    # 6. V-flip
    # ------------------------------------------------------------------
    def _seed_vflip(self) -> None:
        ops1 = self.users["ops1"]
        deo = self.stores["DEO"]
        vf = VFlip.objects.create(
            store=deo,
            original_brand=self.brands["Louis Philippe"],
            season=SS26,
            created_by=ops1,
        )
        identity = resolve_line_identity(deo.id, "LP-SLIM-WHT-38", SS26)
        VFlipLine.objects.create(vflip=vf, sku_code="LP-SLIM-WHT-38", qty=2, **identity)
        request_document_approval(vf, requested_by=ops1)
        approval = approval_for(vf)
        if approval is not None and approval.status == ApprovalStatus.PENDING:
            decide(approval, actor=self.users["owner"], action="approve")
        post_vflip(vf, user=ops1)
        self.stdout.write(f"  V-flip {vf.doc_number} @ DEO: LP stock flipped to owned")

    # ------------------------------------------------------------------
    # 7. stocktakes
    # ------------------------------------------------------------------
    def _seed_stocktakes(self) -> None:
        # HZB: a full blind count with two small variances, applied.
        hzb = self.stores["HZB"]
        st = open_stocktake(hzb, user=self.users["hzb.manager"])
        session = open_session(st, scope="store", user=self.users["hzb.manager"])
        scans = {
            row.sku_code: row.net_qty
            for row in StockOnHand.objects.filter(store=hzb, net_qty__gt=0)
        }
        scans["USP-TEE-WHT-L"] -= 1  # one tee missing
        scans["SPY-TEE-RED-M"] += 1  # one tee extra
        record_scans(session, {k: v for k, v in scans.items() if v > 0})
        submit_session(session)
        apply_variance(st, user=self.users["ops1"])
        self.stdout.write("  Stocktake @ HZB: counted, variance applied")

        # DUM: a brand count still in progress.
        st2 = open_stocktake(self.stores["DUM"], user=self.users["dum.manager"])
        s2 = open_session(st2, scope="brand", scope_value="Jockey", user=self.users["dum.manager"])
        record_scans(s2, {"JKY-TRK-NVY-L": 10})
        self.stdout.write("  Stocktake @ DUM: Jockey count in progress")

    # ------------------------------------------------------------------
    # 8. money
    # ------------------------------------------------------------------
    def _seed_money(self) -> None:
        acct = self.users["ops1"]
        payments = [
            ("abfrl", 50_000, "Part payment against Madura PT bills", "neft", "BANK"),
            ("blackberrys", 40_000, "Payment for suit consignment", "neft", "BANK"),
            ("credo", 25_000, "Mufti account settlement", "upi", "UPI"),
            ("page", 8_000, "Jockey monthly settlement", "cash", "CASH"),
            ("kewalkiran", 15_000, "Killer AW25 part payment", "neft", "BANK"),
        ]
        for code, rupees, desc, mode, account in payments:
            post_vendor_payment(
                self.vendors[code],
                rupees_to_paise(rupees),
                desc,
                acct,
                mode=mode,
                account=account,
            )
        self.stdout.write(f"  Vendor payments: {len(payments)} posted")

        movements = [
            ("in", 45_230, "Cash sales deposit — DEO counter", "CASH", "cash"),
            ("in", 23_410, "UPI collections — BKR", "UPI", "upi"),
            ("in", 500_000, "Owner capital infusion", "BANK", "neft"),
            ("out", 8_750, "Store housekeeping & supplies — DEO", "CASH", "cash"),
            ("out", 12_400, "Freight — Ranchi to Deoghar cartons", "CASH", "cash"),
            ("out", 18_000, "Electricity bill — HZB", "BANK", "netbanking"),
        ]
        for direction, rupees, desc, account, mode in movements:
            post_cash_movement(
                direction, rupees_to_paise(rupees), desc, acct, account=account, mode=mode
            )
        self.stdout.write(f"  Cash/bank movements: {len(movements)} posted")
