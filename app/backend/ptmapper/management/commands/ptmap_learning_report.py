"""The self-improvement dashboard: is the mapper actually learning?

Two views:

  * **Corrections per file, by upload week** — the KPI that should trend to zero as
    learned rules absorb the recurring fixes.
  * **Per learned-rule live precision** — for each approved rule, later corrections
    where the rule *fired* (provenance ``alias``) yet a human overrode it to a
    different value. A non-zero count is a ``DEMOTE?`` flag: the rule may be wrong.

Read-only. Pair it with ``ptmap_mine`` on the daily cron to watch the loop close.

    python manage.py ptmap_learning_report
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.management.base import BaseCommand

from ptmapper.engine import norm
from ptmapper.models import CorrectionEvent, LookupProposal, PtFile


def _week(dt: Any) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


class Command(BaseCommand):
    help = "Corrections-per-file KPI + per-learned-rule live precision."

    def handle(self, *args: Any, **opts: Any) -> None:
        w = self.stdout.write

        # --- KPI: corrections per sent file, by upload week -------------------
        file_corr: dict[int, int] = defaultdict(int)
        for (fid,) in CorrectionEvent.objects.filter(
            pt_file__draft_stage=PtFile.DraftStage.SENT
        ).values_list("pt_file_id"):
            if fid is not None:
                file_corr[fid] += 1

        weeks: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # week -> [files, corrections]
        for pt in PtFile.objects.filter(draft_stage=PtFile.DraftStage.SENT).values(
            "id", "created_at"
        ):
            wk = _week(pt["created_at"])
            weeks[wk][0] += 1
            weeks[wk][1] += file_corr.get(pt["id"], 0)

        w("=" * 68)
        w("CORRECTIONS PER FILE, BY UPLOAD WEEK  (the KPI → 0)")
        w(f"  {'WEEK':<10} {'FILES':>6} {'CORRECTIONS':>12} {'PER FILE':>10}")
        for wk in sorted(weeks):
            files_n, corr_n = weeks[wk]
            per = corr_n / files_n if files_n else 0.0
            bar = "#" * min(40, int(per))
            w(f"  {wk:<10} {files_n:>6} {corr_n:>12} {per:>10.1f}  {bar}")
        if not weeks:
            w("  (no sent files yet — nothing to measure)")

        # --- per learned-rule live precision ---------------------------------
        w("\n" + "=" * 68)
        w("LEARNED-RULE LIVE PRECISION  (later human overrides after the rule fired)")
        approved = LookupProposal.objects.filter(status=LookupProposal.Status.APPROVED)
        flagged = 0
        for p in approved.order_by("dimension", "brand", "source_key"):
            overrides = CorrectionEvent.objects.filter(
                dimension=p.dimension, provenance_before="alias"
            ).exclude(new_value=p.target_value)
            if p.brand:
                overrides = overrides.filter(brand=p.brand)
            if p.applied_at:
                overrides = overrides.filter(created_at__gt=p.applied_at)
            n = sum(1 for e in overrides if norm(e.raw_value) == p.source_key)
            if n:
                flagged += 1
                scope = p.brand or "GLOBAL"
                w(
                    f"  DEMOTE? [{p.dimension}·{scope}] {p.source_key!r}→{p.target_value!r}: "
                    f"overridden {n}× since it went live"
                )
        w(f"  {approved.count()} approved rule(s); {flagged} with live overrides.")
        w("=" * 68)
