"""Idempotent foundation seed: roles, the masters spine, and demo users.

Run: `python manage.py seed_foundation`. Safe to re-run — it upserts. It also
(re)writes `memory/test_credentials.md` in the checkout (override with
`SEED_CREDENTIALS_PATH`) so the testing/fork agents always have current logins.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import NAV_GROUPS, Role, User
from accounts.rbac_matrix import section_access_for
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from vendors.models import Booking, BookingLine, Vendor

# Demo logins (documented credentials) must NOT be (re)created on a production
# deploy. Gate them behind SEED_DEMO (default on, so preview/CI keep working);
# set SEED_DEMO=0 in production.
SEED_DEMO = os.environ.get("SEED_DEMO", "1") == "1"

ROLES: list[dict[str, Any]] = [
    {
        "code": "owner",
        "name": "Owner / Director",
        "landing_page": "owner",
        "nav_groups": list(NAV_GROUPS),
        "description": "Sees the whole business; dashboards, approvals, sign-offs.",
    },
    {
        "code": "store_manager",
        "name": "Store Manager",
        "landing_page": "store",
        "nav_groups": ["home", "store_ops", "documents", "ledgers", "controls", "outbound"],
        "description": "Owns one store's floor; selling, receiving, approvals within tier.",
    },
    {
        "code": "store_staff",
        "name": "Store Staff / Cashier",
        "landing_page": "store",
        "nav_groups": ["home", "store_ops", "documents", "outbound"],
        "description": "Runs the till in one store; bills, exchanges, receives, counts.",
    },
    {
        "code": "warehouse",
        "name": "Warehouse / Inward Operator",
        "landing_page": "warehouse",
        "nav_groups": ["home", "documents", "ledgers", "store_ops", "outbound"],
        "description": "Receives goods, builds PTs, fills barcodes, proposes splits.",
    },
    {
        "code": "accounts",
        "name": "Accounts / Finance",
        "landing_page": "finance",
        "nav_groups": ["home", "documents", "ledgers", "controls", "intelligence", "outbound"],
        "description": "Owns money — payables, payments, collection & bank audit, Tally.",
    },
    {
        "code": "brand_manager",
        "name": "Brand Manager",
        "landing_page": "home",
        "nav_groups": ["home", "documents", "intelligence"],
        "description": "Owns assigned brands across stores — bookings, offers, brand reports.",
    },
    {
        "code": "ho_ops",
        "name": "HO Operations / Buyer",
        "landing_page": "ops",
        "nav_groups": [
            "home",
            "master_data",
            "documents",
            "ledgers",
            "controls",
            "intelligence",
            "outbound",
        ],
        "description": "HO operating core — bookings, transfers, offers, intelligence.",
    },
    {
        "code": "data_steward",
        "name": "HO Data Steward",
        "landing_page": "masters",
        "nav_groups": ["home", "master_data"],
        "description": "Single steward of master data — vendors/brands/SKU/season/taxonomy.",
    },
    {
        "code": "it_admin",
        "name": "System / IT Admin",
        "landing_page": "owner",
        "nav_groups": list(NAV_GROUPS),
        "description": "Owns users, RBAC, and all integration/adapter/config plumbing.",
    },
]

# Usernames granted Django-superuser break-glass. A superuser bypasses the whole
# RBAC matrix (manage on every section) and reaches Django `/admin`, so it is
# kept as its own account, separate from every business persona — including
# Owner. That way the matrix is genuinely enforced for real people (Owner sees
# only what the sheet grants, Admin has no Money) and stays auditable; god-mode
# lives in one clearly-labelled break-glass login instead of a daily persona.
SUPERUSERS = {"superadmin"}

# (username, password, role_code, scope_type, store_codes, full_name, brand_codes)
# `brand_codes` only applies to the `brand` scope — a brand manager works across
# every store but only inside their own brands, so the top bar gives them a brand
# filter instead of a unit list (#88).
USERS: list[tuple[str, str, str, str, list[str], str, list[str]]] = [
    ("superadmin", "Super@123", "it_admin", "all", [], "System Superadmin (break-glass)", []),
    ("admin", "Admin@123", "it_admin", "all", [], "IT Admin", []),
    ("owner", "Owner@123", "owner", "all", [], "K. D. Proprietor", []),
    ("ops1", "Ops@123", "ho_ops", "all", [], "Head-Office Ops", []),
    ("accounts1", "Acct@123", "accounts", "all", [], "Patna Accountant", []),
    (
        "brand1",
        "Brand@123",
        "brand_manager",
        "brand",
        [],
        "Madura Brand Manager",
        ["louis-philippe", "van-heusen", "allen-solly", "peter-england"],
    ),
    ("wh.patna", "Wh@123", "warehouse", "all", [], "Patna Warehouse", []),
    ("steward", "Steward@123", "data_steward", "all", [], "Data Steward", []),
    ("deo.manager", "Store@123", "store_manager", "store", ["DEO"], "Deoghar Manager", []),
    ("deo.cashier", "Store@123", "store_staff", "store", ["DEO"], "Deoghar Cashier", []),
    ("bkr.manager", "Store@123", "store_manager", "store", ["BKR"], "Bokaro Manager", []),
    ("bkr.cashier", "Store@123", "store_staff", "store", ["BKR"], "Bokaro Cashier", []),
    ("hzb.manager", "Store@123", "store_manager", "store", ["HZB"], "Hazaribagh Manager", []),
    ("dum.manager", "Store@123", "store_manager", "store", ["DUM"], "Dumka Manager", []),
    ("banka.manager", "Store@123", "store_manager", "store", ["BANKA"], "Banka Manager", []),
    ("banka.cashier", "Store@123", "store_staff", "store", ["BANKA"], "Banka Cashier", []),
    ("wh.ranchi", "Wh@123", "warehouse", "store", ["RAN-WH"], "Ranchi Warehouse", []),
]


class Command(BaseCommand):
    help = "Seed foundation roles, masters and demo users (idempotent)."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        self._seed_roles()
        entity, gstins = self._seed_entity_gstins()
        stores = self._seed_stores(gstins)
        self._seed_seasons()
        self._seed_brands()
        self._seed_gst_slab()
        vendors = self._seed_vendors()
        if SEED_DEMO:
            self._seed_users(entity, stores)
            self._seed_sample_booking(vendors, stores)
            self._write_credentials()
            self.stdout.write(self.style.SUCCESS("Foundation seed complete (incl. demo users)."))
        else:
            self.stdout.write(
                self.style.SUCCESS("Foundation seed complete (SEED_DEMO=0: demo users skipped).")
            )

    def _seed_roles(self) -> None:
        for r in ROLES:
            Role.objects.update_or_create(
                code=r["code"],
                defaults={
                    "name": r["name"],
                    "landing_page": r["landing_page"],
                    "nav_groups": r["nav_groups"],
                    # The SIDEBAR RBAC contract (#85). Re-seeding overwrites it back
                    # to the sheet default; a live admin's retune is a deliberate
                    # data edit they'd re-apply, same as nav_groups here.
                    "section_access": section_access_for(r["code"]),
                    "description": r["description"],
                    "is_system": True,
                    "is_active": True,
                },
            )

    def _seed_entity_gstins(self) -> tuple[LegalEntity, dict[str, Gstin]]:
        entity, _ = LegalEntity.objects.update_or_create(
            code="kdps",
            defaults={"name": "KDPS Lifestyle Pvt Ltd", "pan": "AAACK1234M"},
        )
        bihar, _ = Gstin.objects.update_or_create(
            gstin="10AAACK1234M1Z5",
            defaults={"legal_entity": entity, "state_code": "10", "state_name": "Bihar"},
        )
        jhk, _ = Gstin.objects.update_or_create(
            gstin="20AAACK1234M1Z3",
            defaults={"legal_entity": entity, "state_code": "20", "state_name": "Jharkhand"},
        )
        return entity, {"bihar": bihar, "jharkhand": jhk}

    def _seed_stores(self, gstins: dict[str, Gstin]) -> dict[str, Store]:
        rows = [
            ("DEO", "Deoghar", "store", "jharkhand", "Deoghar"),
            ("BKR", "Bokaro", "store", "jharkhand", "Bokaro"),
            ("HZB", "Hazaribagh", "store", "jharkhand", "Hazaribagh"),
            ("DUM", "Dumka", "store", "jharkhand", "Dumka"),
            ("BANKA", "Banka", "store", "bihar", "Banka"),
            ("RAN-WH", "Ranchi Central Warehouse", "warehouse", "jharkhand", "Ranchi"),
        ]
        out: dict[str, Store] = {}
        for code, name, stype, state, city in rows:
            store, _ = Store.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "store_type": stype,
                    "gstin": gstins[state],
                    "city": city,
                },
            )
            out[code] = store
        return out

    def _seed_seasons(self) -> None:
        for code, name, status, order in [
            ("SS26", "Spring/Summer 2026", "open", 3),
            ("AW25", "Autumn/Winter 2025", "eoss", 2),
            ("SS25", "Spring/Summer 2025", "closed", 1),
        ]:
            Season.objects.update_or_create(
                code=code, defaults={"name": name, "status": status, "sort_order": order}
            )

    def _seed_brands(self) -> None:
        rows = [
            ("louis-philippe", "Louis Philippe", "brand_owned", "uncapped"),
            ("van-heusen", "Van Heusen", "brand_owned", "uncapped"),
            ("allen-solly", "Allen Solly", "brand_owned", "rolling"),
            ("peter-england", "Peter England", "owned", "capped"),
            ("mufti", "Mufti", "owned", "none"),
            ("blackberry", "Blackberrys", "owned", "capped"),
            ("jockey", "Jockey", "owned", "none"),
            ("us-polo", "U.S. Polo Assn.", "brand_owned", "uncapped"),
            ("spykar", "Spykar", "owned", "none"),
            ("killer", "Killer", "owned", "none"),
        ]
        for code, name, ownership, terms in rows:
            Brand.objects.update_or_create(
                code=code,
                defaults={"name": name, "ownership": ownership, "return_terms": terms},
            )

    def _seed_gst_slab(self) -> None:
        from masters.models import GstSlab

        GstSlab.objects.update_or_create(
            name="Apparel (GST 2.0)",
            defaults={
                "threshold_paise": 250000,
                "rate_below": 5,
                "rate_above": 18,
                "effective_from": datetime.date(2025, 9, 22),
            },
        )

    def _seed_vendors(self) -> dict[str, Vendor]:
        rows = [
            (
                "abfrl",
                "Aditya Birla Fashion (Madura)",
                "Bengaluru",
                "29AAACX1234M1Z1",
                "29",
                "Karnataka",
                ["louis-philippe", "van-heusen", "allen-solly", "peter-england"],
            ),
            (
                "arvind",
                "Arvind Fashions",
                "Bengaluru",
                "29AAACA5678M1Z2",
                "29",
                "Karnataka",
                ["us-polo", "spykar"],
            ),
            (
                "credo",
                "Credo Brands (Mufti)",
                "Mumbai",
                "27AAACC9012M1Z3",
                "27",
                "Maharashtra",
                ["mufti"],
            ),
            (
                "blackberrys",
                "Blackberrys Menswear",
                "New Delhi",
                "07AAACB3456M1Z4",
                "07",
                "Delhi",
                ["blackberry"],
            ),
            (
                "page",
                "Page Industries (Jockey)",
                "Bengaluru",
                "29AAACP7890M1Z5",
                "29",
                "Karnataka",
                ["jockey"],
            ),
            (
                "kewalkiran",
                "Kewal Kiran (Killer)",
                "Mumbai",
                "27AAACK2345M1Z6",
                "27",
                "Maharashtra",
                ["killer"],
            ),
        ]
        out: dict[str, Vendor] = {}
        for code, name, city, gstin, sc, sn, brand_codes in rows:
            vendor, _ = Vendor.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "city": city,
                    "gstin": gstin,
                    "state_code": sc,
                    "state_name": sn,
                    "payment_terms": "Net 30",
                },
            )
            vendor.brands.set(Brand.objects.filter(code__in=brand_codes))
            out[code] = vendor
        return out

    def _seed_sample_booking(self, vendors: dict[str, Vendor], stores: dict[str, Store]) -> None:
        season = Season.objects.filter(code="SS26").first()
        brand = Brand.objects.filter(code="peter-england").first()
        vendor = vendors.get("abfrl")
        if not (season and brand and vendor):
            return
        booking, created = Booking.objects.get_or_create(
            number="BK-SS26-0001",
            defaults={
                "vendor": vendor,
                "brand": brand,
                "season": season,
                "destination_store": stores.get("DEO"),
                "status": Booking.Status.BOOKED,
                "vendor_ref": "PE/ORD/2026/118",
                "ownership": brand.ownership,
                "return_terms": brand.return_terms,
            },
        )
        if created:
            # A multi-store booking: shirts inherit the booking default (DEO), the
            # trousers are explicitly routed to a second store (BKR) — demonstrating
            # the "default destination, override per line" rule.
            for style, size, qty, mrp, store_code in [
                ("PE-FSHIRT-001", "39", 12, 1799_00, None),
                ("PE-FSHIRT-001", "40", 18, 1799_00, None),
                ("PE-TROUSER-100", "32", 10, 2499_00, "BKR"),
                ("PE-TROUSER-100", "34", 8, 2499_00, "BKR"),
            ]:
                BookingLine.objects.create(
                    booking=booking,
                    store=stores.get(store_code) if store_code else None,
                    style_code=style,
                    size=size,
                    booked_qty=qty,
                    mrp_paise=mrp,
                )
            booking.estimated_value_paise = sum(
                line.booked_qty * (line.mrp_paise or 0) for line in booking.lines.all()
            )
            booking.save(update_fields=["estimated_value_paise"])

    def _seed_users(self, entity: LegalEntity, stores: dict[str, Store]) -> None:
        for username, password, role_code, scope, store_codes, full_name, brand_codes in USERS:
            role = Role.objects.filter(code=role_code).first()
            # Only the dedicated break-glass account is a Django superuser (see
            # SUPERUSERS). Every business persona — `admin`/it_admin and `owner`
            # included — is a normal user enforced by `Role.section_access`, so
            # the ratified matrix (e.g. Admin = no Money) actually applies.
            is_super = username in SUPERUSERS
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    "full_name": full_name,
                    "role": role,
                    "scope_type": scope,
                    "entity": entity if scope != "all" else None,
                    "is_active": True,
                    "is_staff": is_super,
                    "is_superuser": is_super,
                },
            )
            # Set the password only when the user is first created — never overwrite
            # an operator-changed password on a re-seed / redeploy.
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
            user.stores.set([stores[c] for c in store_codes if c in stores])
            user.brands.set(Brand.objects.filter(code__in=brand_codes))

    def _write_credentials(self) -> None:
        lines = [
            "# KDPS — Test Credentials",
            "",
            "Foundation demo logins (seeded by `python manage.py seed_foundation`).",
            "Login at the app root; API at `/api/auth/login`.",
            "",
            "| Username | Password | Role | Scope |",
            "|---|---|---|---|",
        ]
        for username, password, role_code, scope, store_codes, _, brand_codes in USERS:
            units = store_codes or brand_codes
            scope_txt = f"{scope} ({','.join(units)})" if units else scope
            lines.append(f"| {username} | {password} | {role_code} | {scope_txt} |")
        lines += [
            "",
            "`superadmin` is the only Django superuser (break-glass: bypasses the RBAC "
            "matrix, reaches `/admin`). Every other login — including `admin` (it_admin) "
            "and `owner` — is a normal user enforced by the section-access matrix.",
            "",
        ]
        # Best-effort convenience dump of the demo logins. The data is already in
        # the DB, so never let a read-only or absent filesystem (e.g. Render's
        # build container) fail the seed.
        #
        # Resolved from the checkout, not hardcoded: the old "/app/memory/..."
        # default was the Emergent container's layout, so on a dev machine every
        # seed skipped the write against read-only "/app".
        default_path = Path(settings.BASE_DIR).parent.parent / "memory" / "test_credentials.md"
        path = Path(os.environ.get("SEED_CREDENTIALS_PATH", str(default_path)))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            self.stdout.write(self.style.WARNING(f"Skipped writing {path}: {exc}"))
