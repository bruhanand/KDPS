"""The two checks the alerts job runs, and the sync that keeps their open
alerts matching what is true right now (#77).

Both checks return every currently-true instance of their kind, keyed by a
dedupe key; ``_sync_kind`` opens what's new, leaves what's still open alone,
and resolves what stopped being true. A later alert kind (dead stock, another
deadline) is another check function returning the same ``AlertHit`` shape, not
a new mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from core.documents import DocStatus
from masters.models import Brand
from outbound.models import ReturnSource, StoreTransfer
from outbound.returnable import returnable_pool_all

from .models import Alert, AlertKind, AlertPolicy, AlertStatus


@dataclass(frozen=True)
class AlertHit:
    """One currently-true instance of an alert kind, before it becomes a row."""

    dedupe_key: str
    title: str
    store_id: int | None
    brand: str
    object_id: int | None
    due_date: date | None
    threshold_days: int | None


def _thresholds(kind: str) -> list[int]:
    """This kind's configured thresholds, largest first — data, not code
    (Rule 12). No policy row means the check is switched off, not defaulted."""
    policy = AlertPolicy.objects.filter(kind=kind).first()
    return sorted(policy.thresholds_days, reverse=True) if policy else []


def check_in_transit_aging(today: date) -> list[AlertHit]:
    """Dispatched transfers with pieces still on the road past the configured
    number of days — transit loss without anyone remembering to check.

    One threshold for this kind: "not received within N days" (the corpus's own
    words). A transfer with a receipt is done; a transfer whose scan gap has
    already been closed (nothing left ``in_transit``) has nothing to chase.
    """
    thresholds = _thresholds(AlertKind.IN_TRANSIT_AGING)
    if not thresholds:
        return []
    days = thresholds[0]
    cutoff = today - timedelta(days=days)

    hits: list[AlertHit] = []
    qs = (
        StoreTransfer.objects.filter(docstatus=DocStatus.SUBMITTED, receipt__isnull=True)
        .exclude(dispatch_date__isnull=True)
        .filter(dispatch_date__date__lte=cutoff)
        .select_related("destination_store")
        .prefetch_related("lines")
    )
    for transfer in qs:
        qty_stuck = sum(line.qty_in_transit for line in transfer.lines.all())
        if qty_stuck <= 0:
            continue
        dispatched_on = timezone.localtime(transfer.dispatch_date).date()
        overdue_by = (today - dispatched_on).days - days
        hits.append(
            AlertHit(
                dedupe_key=f"transfer:{transfer.id}",
                title=(
                    f"{transfer.doc_number or 'Transfer'} to {transfer.destination_store.name} — "
                    f"{qty_stuck} pc(s) still in transit, {overdue_by} day(s) past the "
                    f"{days}-day limit"
                ),
                store_id=transfer.destination_store_id,
                brand="",
                object_id=transfer.id,
                due_date=dispatched_on + timedelta(days=days),
                threshold_days=days,
            )
        )
    return hits


def check_return_window(today: date) -> list[AlertHit]:
    """Season-end holdings inside a brand's negotiated return window, counting
    down through the configured days-left thresholds (30/15/7).

    Confirmed-damage holdings carry no window (returnable.py) and are never
    alerted here; an already-expired holding is not offered back to the brand
    at all, so it stops crossing new thresholds.

    One alert per holding, not one per threshold: a holding may have crossed
    more than one threshold by the time the job first sees it (a first-ever
    run, or one that missed a few days), but a countdown is one reminder that
    tightens, not three permanent ones stacked on top of each other — so only
    the tightest threshold already crossed is reported, and it re-fires under
    the *same* dedupe key as the countdown continues, refreshing the alert
    already open rather than opening a second one beside it.
    """
    thresholds = _thresholds(AlertKind.RETURN_WINDOW)
    if not thresholds:
        return []

    hits: list[AlertHit] = []
    # `takes_returns` is derived from the two commercial-model axes, not a
    # column — filtered in Python, the same as `returnable_pool_all` does it.
    for brand in Brand.objects.filter(is_active=True):
        if not brand.takes_returns:
            continue
        for row in returnable_pool_all(brand, today=today):
            if row.source != ReturnSource.SEASON_END or row.expired or row.days_left is None:
                continue
            crossed = [t for t in thresholds if row.days_left <= t]
            if not crossed:
                continue
            tightest = min(crossed)
            hits.append(
                AlertHit(
                    dedupe_key=f"return_window:{brand.id}:{row.store_id}:{row.sku_code}",
                    title=(
                        f"{brand.name} at {row.store_code} — {row.sku_code} "
                        f"({row.qty} pc(s)) must go back within {row.days_left} day(s) — "
                        f"past the {tightest}-day mark"
                    ),
                    store_id=row.store_id,
                    brand=brand.name,
                    object_id=None,
                    due_date=row.window_date,
                    threshold_days=tightest,
                )
            )
    return hits


def _sync_kind(kind: str, kind_label: str, hits: list[AlertHit]) -> None:
    """Open what's new, resolve what stopped being true, and refresh what's
    still open — a holding's countdown moves even while its alert stays open,
    so the title/threshold on an existing row must track it, not freeze at
    whatever it said the day the row was born."""
    current_keys = {hit.dedupe_key for hit in hits}
    (
        Alert.objects.filter(kind=kind, status=AlertStatus.OPEN)
        .exclude(dedupe_key__in=current_keys)
        .update(status=AlertStatus.RESOLVED, resolved_at=timezone.now())
    )
    for hit in hits:
        Alert.objects.update_or_create(
            kind=kind,
            dedupe_key=hit.dedupe_key,
            status=AlertStatus.OPEN,
            defaults={
                "kind_label": kind_label,
                "title": hit.title,
                "store_id": hit.store_id,
                "brand": hit.brand,
                "object_id": hit.object_id,
                "due_date": hit.due_date,
                "threshold_days": hit.threshold_days,
            },
        )


def run_alert_checks(today: date | None = None) -> dict[str, int]:
    """Run both checks and sync the alerts table. Returns the hit counts, for
    the job's own log line."""
    today = today or timezone.localdate()
    aging = check_in_transit_aging(today)
    window = check_return_window(today)
    _sync_kind(AlertKind.IN_TRANSIT_AGING, AlertKind.IN_TRANSIT_AGING.label, aging)
    _sync_kind(AlertKind.RETURN_WINDOW, AlertKind.RETURN_WINDOW.label, window)
    return {"in_transit_aging": len(aging), "return_window": len(window)}
