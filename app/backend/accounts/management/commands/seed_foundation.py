"""Idempotent foundation seed: roles, the masters spine, and demo users.

Run: `python manage.py seed_foundation`. Safe to re-run — it upserts. It also
(re)writes `/app/memory/test_credentials.md` so the testing/fork agents always
have current logins.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import NAV_GROUPS, Role, User
from masters.models import Brand, Gstin, LegalEntity, Season, Store

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
        "nav_groups": ["home", "store_ops", "documents", "ledgers", "controls"],
        "description": "Owns one store's floor; selling, receiving, approvals within tier.",
    },
    {
        "code": "store_staff",
        "name": "Store Staff / Cashier",
        "landing_page": "store",
        "nav_groups": ["home", "store_ops", "documents"],
        "description": "Runs the till in one store; bills, exchanges, receives, counts.",
    },
    {
        "code": "warehouse",
        "name": "Warehouse / Inward Operator",
        "landing_page": "warehouse",
        "nav_groups": ["home", "documents", "ledgers", "store_ops"],
        "description": "Receives goods, builds PTs, fills barcodes, proposes splits.",
    },
    {
        "code": "accounts",
        "name": "Accounts / Finance",
        "landing_page": "finance",
        "nav_groups": ["home", "documents", "ledgers", "controls", "intelligence"],
        "description": "Owns money — payables, payments, collection & bank audit, Tally.",
    },
    {
        "code": "ho_ops",
        "name": "HO Operations / Buyer",
        "landing_page": "ops",
        "nav_groups": ["home", "master_data", "documents", "ledgers", "controls", "intelligence"],
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

# (username, password, role_code, scope_type, store_codes, full_name)
USERS: list[tuple[str, str, str, str, list[str], str]] = [
    ("admin", "Admin@123", "it_admin", "all", [], "System Admin"),
    ("owner", "Owner@123", "owner", "all", [], "K. D. Proprietor"),
    ("ops1", "Ops@123", "ho_ops", "all", [], "Head-Office Ops"),
    ("accounts1", "Acct@123", "accounts", "all", [], "Patna Accountant"),
    ("wh.patna", "Wh@123", "warehouse", "all", [], "Patna Warehouse"),
    ("steward", "Steward@123", "data_steward", "all", [], "Data Steward"),
    ("deo.manager", "Store@123", "store_manager", "store", ["DEO"], "Deoghar Manager"),
    ("deo.cashier", "Store@123", "store_staff", "store", ["DEO"], "Deoghar Cashier"),
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
        self._seed_users(entity, stores)
        self._write_credentials()
        self.stdout.write(self.style.SUCCESS("Foundation seed complete."))

    def _seed_roles(self) -> None:
        for r in ROLES:
            Role.objects.update_or_create(
                code=r["code"],
                defaults={
                    "name": r["name"],
                    "landing_page": r["landing_page"],
                    "nav_groups": r["nav_groups"],
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
            ("PAT-WH", "Patna Central Warehouse", "warehouse", "bihar", "Patna"),
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

    def _seed_users(self, entity: LegalEntity, stores: dict[str, Store]) -> None:
        for username, password, role_code, scope, store_codes, full_name in USERS:
            role = Role.objects.filter(code=role_code).first()
            is_admin = username == "admin"
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "full_name": full_name,
                    "role": role,
                    "scope_type": scope,
                    "entity": entity if scope != "all" else None,
                    "is_active": True,
                    "is_staff": is_admin,
                    "is_superuser": is_admin,
                },
            )
            user.set_password(password)
            user.save()
            user.stores.set([stores[c] for c in store_codes if c in stores])

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
        for username, password, role_code, scope, store_codes, _ in USERS:
            scope_txt = f"{scope} ({','.join(store_codes)})" if store_codes else scope
            lines.append(f"| {username} | {password} | {role_code} | {scope_txt} |")
        lines += [
            "",
            "`admin` is the Django superuser (also reaches `/admin`).",
            "",
        ]
        path = Path("/app/memory/test_credentials.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
