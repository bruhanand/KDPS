"""Rebuild the materialised projections from the append-only stock ledger.

`StockOnHand` (at-location) and `InTransitStock` (the in-transit bucket per
transfer) are caches maintained inside each posting transaction; this command
recomputes both from scratch (the ledger is the source of truth) — useful after
a backfill, a bulk import, or any doubt about drift. Idempotent.

Transit legs (``transit_in``/``transit_out``) ride on the *source* store but
are NOT at-location stock — they aggregate into `InTransitStock` keyed by the
transfer's doc number, never into `StockOnHand`.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from stockledger.models import InTransitStock, StockLedgerEntry, StockOnHand, merch_dims

TRANSIT_KINDS = {StockLedgerEntry.Kind.TRANSIT_IN, StockLedgerEntry.Kind.TRANSIT_OUT}


class Command(BaseCommand):
    help = "Recompute StockOnHand + InTransitStock from the append-only stock ledger."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        agg: dict[tuple[int, str], list[int]] = {}
        desc: dict[tuple[int, str], dict[str, Any]] = {}
        transit_agg: dict[tuple[str, str], list[int]] = {}
        transit_desc: dict[tuple[str, str], dict[str, Any]] = {}

        for e in StockLedgerEntry.objects.all().iterator():
            if e.kind in TRANSIT_KINDS:
                tkey = (e.doc_number, e.sku_code)
                t = transit_agg.setdefault(tkey, [0, 0])
                t[0] += e.qty
                t[1] += int(e.amount or 0)
                if e.qty > 0:
                    transit_desc[tkey] = {
                        "source_store_id": e.store_id,
                        "gstin_id": e.gstin_id,
                        **merch_dims(e),
                    }
                continue

            key = (e.store_id, e.sku_code)
            a = agg.setdefault(key, [0, 0])
            a[0] += e.qty
            a[1] += int(e.amount or 0)
            if e.qty > 0:
                d = desc.get(key)
                if d is None or e.id > d["id"]:
                    desc[key] = {
                        "id": e.id,
                        "gstin_id": e.gstin_id,
                        "design": e.design,
                        "color": e.color,
                        "size": e.size,
                        "brand": e.brand,
                        "season": e.season,
                        "item": e.item,
                        "hsn": e.hsn,
                    }

        StockOnHand.objects.all().delete()
        rows = []
        for (store_id, sku_code), (q, v) in agg.items():
            d = desc.get((store_id, sku_code), {})
            rows.append(
                StockOnHand(
                    store_id=store_id,
                    sku_code=sku_code,
                    gstin_id=d.get("gstin_id"),
                    design=d.get("design", "") or "",
                    color=d.get("color", "") or "",
                    size=d.get("size", "") or "",
                    brand=d.get("brand", "") or "",
                    season=d.get("season", "") or "",
                    item=d.get("item", "") or "",
                    hsn=d.get("hsn", "") or "",
                    net_qty=q,
                    net_value_paise=v,
                )
            )
        StockOnHand.objects.bulk_create(rows)

        # In-transit bucket: destination comes from the transfer document
        # (lazy lookup — the generic ledger app holds no FK to outbound).
        StoreTransfer = apps.get_model("outbound", "StoreTransfer")
        destinations = dict(
            StoreTransfer.objects.filter(
                doc_number__in={doc for doc, _ in transit_agg}
            ).values_list("doc_number", "destination_store_id")
        )
        InTransitStock.objects.all().delete()
        transit_rows = []
        for (doc_number, sku_code), (q, v) in transit_agg.items():
            if q == 0:
                continue
            d = transit_desc.get((doc_number, sku_code), {})
            source_store_id = d.get("source_store_id")
            destination_store_id = destinations.get(doc_number)
            if source_store_id is None or destination_store_id is None:
                self.stderr.write(
                    f"Skipping orphan transit rows for {doc_number}/{sku_code}: "
                    "no positive transit leg or no matching transfer document."
                )
                continue
            transit_rows.append(
                InTransitStock(
                    transfer_doc_number=doc_number,
                    sku_code=sku_code,
                    source_store_id=source_store_id,
                    destination_store_id=destination_store_id,
                    gstin_id=d.get("gstin_id"),
                    design=d.get("design", "") or "",
                    color=d.get("color", "") or "",
                    size=d.get("size", "") or "",
                    brand=d.get("brand", "") or "",
                    season=d.get("season", "") or "",
                    item=d.get("item", "") or "",
                    hsn=d.get("hsn", "") or "",
                    qty=q,
                    value_paise=v,
                )
            )
        InTransitStock.objects.bulk_create(transit_rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt {len(rows)} StockOnHand + {len(transit_rows)} InTransitStock rows."
            )
        )
