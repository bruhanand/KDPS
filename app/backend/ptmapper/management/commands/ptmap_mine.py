"""Deterministic corrections miner — turn the human-correction log into staged
learning proposals (never live rules; a human still approves each one — Rule 8).

Mines only ``CorrectionEvent`` rows whose file *reached Patna* (``draft_stage=SENT``
— the D1 trust gate; events whose file was deleted have a NULL FK and are excluded
by the join). Groups by ``(dimension, norm(raw), brand)`` and proposes:

  * a **brand-scoped** rule when one target has ``>= --min-support`` events across
    ``>= 2`` distinct files with zero conflicting targets;
  * a **global** rule only when ``>= 2`` distinct brands independently agree on the
    same single target.

Pairs already covered by an equal ``Lookup`` are skipped; a *disagreeing* Lookup is
reported as a demotion candidate (flagged, never auto-deleted — Rule 5). Each new
proposal is shadow-checked; a conflict flips it to ``auto_rejected`` with the detail.
Idempotent via the partial-unique open-proposal index, so it is safe to cron daily.

    python manage.py ptmap_mine
    python manage.py ptmap_mine --min-support 5 --include-fill-all
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.management.base import BaseCommand

from ptmapper import learning
from ptmapper.engine import norm
from ptmapper.learning import LEARNABLE_DIMS
from ptmapper.models import ControlledValue, CorrectionEvent, Lookup, LookupProposal, PtFile


def _master_vocab() -> dict[str, set[str]]:
    vocab: dict[str, set[str]] = {}
    for cv in ControlledValue.objects.filter(dimension__in=LEARNABLE_DIMS):
        vocab.setdefault(cv.dimension, set()).add(cv.value)
    return vocab


class Command(BaseCommand):
    help = "Mine the correction log into staged learning proposals (SENT files only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--min-support", type=int, default=3)
        parser.add_argument(
            "--include-fill-all",
            action="store_true",
            help="also mine fill_all edits (off by default — a broad fill pairs "
            "coincidental raws with one target).",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        min_support: int = opts["min_support"]
        vocab = _master_vocab()

        events = (
            CorrectionEvent.objects.filter(
                pt_file__draft_stage=PtFile.DraftStage.SENT, dimension__in=LEARNABLE_DIMS
            )
            .exclude(raw_value="")
            .exclude(new_value="")
        )
        if not opts["include_fill_all"]:
            events = events.exclude(edit_kind=CorrectionEvent.EditKind.FILL_ALL)

        # group (dimension, norm(raw)) → [(brand, target, file_id)]
        groups: dict[tuple[str, str], list[tuple[str, str, int]]] = defaultdict(list)
        mined_events = 0
        for e in events.values("dimension", "brand", "raw_value", "new_value", "pt_file_id"):
            dim, target = e["dimension"], e["new_value"]
            if target not in vocab.get(dim, set()):
                continue  # new_value must be a Master value
            key = norm(e["raw_value"])
            if not key:
                continue
            groups[(dim, key)].append((e["brand"], target, e["pt_file_id"]))
            mined_events += 1

        stats = {"proposed": 0, "auto_rejected": 0, "covered": 0}
        demotions: list[str] = []
        conflicts: list[str] = []

        def consider(dim: str, key: str, target: str, brand: str, support: int, files: set) -> None:
            existing = Lookup.objects.filter(dimension=dim, source_key=key, brand=brand).first()
            if existing is not None:
                if existing.target_value != target:
                    scope = brand or "GLOBAL"
                    demotions.append(
                        f"[{dim}·{scope}] {key!r}: rule says {existing.target_value!r} but "
                        f"{support} correction(s) say {target!r}"
                    )
                else:
                    stats["covered"] += 1
                return
            # respect a human rejection of this exact mapping — don't nag on every run
            if LookupProposal.objects.filter(
                dimension=dim,
                source_key=key,
                brand=brand,
                target_value=target,
                status=LookupProposal.Status.REJECTED,
            ).exists():
                return
            proposal = learning.propose(
                dimension=dim,
                source_key=key,
                target_value=target,
                brand=brand,
                origin=LookupProposal.Origin.MINED,
                evidence={"occurrences": support, "files": sorted(files)},
            )
            validation = learning.shadow_check(dim, key, target, brand)
            proposal.validation = validation
            if not validation["ok"]:
                proposal.status = LookupProposal.Status.AUTO_REJECTED
                stats["auto_rejected"] += 1
            else:
                stats["proposed"] += 1
            proposal.save()

        for (dim, key), recs in groups.items():
            branded = [(b, t, f) for (b, t, f) in recs if b]
            targets = {t for (_, t, _) in branded}
            brands = {b for (b, _, _) in branded}
            # global: >= 2 distinct brands, exactly one target between them
            if len(targets) == 1 and len(brands) >= 2:
                consider(
                    dim, key, next(iter(targets)), "", len(branded), {f for (_, _, f) in branded}
                )
                continue
            # else per-brand, brand-scoped
            by_brand: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for b, t, f in branded:
                by_brand[b].append((t, f))
            for b, tf in by_brand.items():
                ts = {t for (t, _) in tf}
                if len(ts) != 1:
                    conflicts.append(f"[{dim}·{b}] {key!r}: {sorted(ts)} (ambiguous — not mined)")
                    continue
                files = {f for (_, f) in tf}
                if len(tf) >= min_support and len(files) >= 2:
                    consider(dim, key, next(iter(ts)), b, len(tf), files)

        w = self.stdout.write
        w("=" * 72)
        w(
            f"Mined {mined_events} correction event(s) in {len(groups)} raw group(s) "
            f"(min-support {min_support}, ≥2 files brand-scoped / ≥2 brands global)."
        )
        w(
            f"  proposed {stats['proposed']} · auto-rejected {stats['auto_rejected']} "
            f"· already-covered {stats['covered']}"
        )
        if demotions:
            w(f"\nDEMOTION CANDIDATES ({len(demotions)}) — a live rule disagrees with corrections:")
            for d in demotions:
                w(f"  ⚠ {d}")
        if conflicts:
            w(f"\nAMBIGUOUS GROUPS ({len(conflicts)}) — corrections disagree, nothing proposed:")
            for c in conflicts[:40]:
                w(f"  · {c}")
        w("=" * 72)
