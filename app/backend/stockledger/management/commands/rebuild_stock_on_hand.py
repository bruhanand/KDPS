"""Rebuild the materialised `StockOnHand` projection from the append-only ledger.

The on-hand table is a cache maintained inside each post/reverse; this command
recomputes it from scratch (the ledger is the source of truth) — useful after a
backfill, a bulk import, or any doubt about drift. Idempotent.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from stockledger.models import StockLedgerEntry, StockOnHand


class Command(BaseCommand):
    help = "Recompute StockOnHand from the append-only stock ledger."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        agg: dict[tuple[int, str], list[int]] = {}
        desc: dict[tuple[int, str], dict] = {}
        for e in StockLedgerEntry.objects.all().iterator():
            key = (e.store_id, e.sku_code)
            a = agg.setdefault(key, [0, 0])
            a[0] += e.qty
            a[1] += e.amount
            if e.qty > 0:
                d = desc.get(key)
                if d is None or e.id > d["id"]:
                    desc[key] = {
                        "id": e.id, "gstin_id": e.gstin_id, "design": e.design,
                        "color": e.color, "size": e.size, "brand": e.brand,
                        "season": e.season, "item": e.item, "hsn": e.hsn,
                    }

        StockOnHand.objects.all().delete()
        rows = []
        for (store_id, sku_code), (q, v) in agg.items():
            d = desc.get((store_id, sku_code), {})
            rows.append(StockOnHand(
                store_id=store_id, sku_code=sku_code, gstin_id=d.get("gstin_id"),
                design=d.get("design", "") or "", color=d.get("color", "") or "",
                size=d.get("size", "") or "", brand=d.get("brand", "") or "",
                season=d.get("season", "") or "", item=d.get("item", "") or "",
                hsn=d.get("hsn", "") or "", net_qty=q, net_value_paise=v,
            ))
        StockOnHand.objects.bulk_create(rows)
        self.stdout.write(self.style.SUCCESS(f"Rebuilt {len(rows)} StockOnHand rows."))
