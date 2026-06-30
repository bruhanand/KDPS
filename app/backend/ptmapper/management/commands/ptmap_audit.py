"""Audit the PT mapper against a folder of real brand files.

Runs the engine over every file (pure read — no DB writes) and reports, per KDPS
derived field, the fill rate (% of rows that resolved to a value) plus the top
unresolved raw values per dimension. This is the mapping-quality yardstick: run it
before and after a seed/engine change to see exactly what improved.

    python manage.py ptmap_audit
    python manage.py ptmap_audit --dir "/path/to/PT FILE" --misses 30
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from ptmapper.engine import run_mapping
from ptmapper.profiles import CONTROLLED

# SEASON, BRAND, COLOR, GENDER, SUB CATEGORY, TYPE, ITEM, FIT, SIZE
DERIVED = list(CONTROLLED.keys())


class Command(BaseCommand):
    help = "Audit PT-mapper fill rates across a folder of real brand files."

    def add_arguments(self, parser) -> None:
        repo_root = Path(settings.BASE_DIR).parent.parent
        default = repo_root / "docs" / "data-from-kdps" / "Q&A-req-recieved" / "PT FILE"
        parser.add_argument("--dir", default=str(default))
        parser.add_argument("--misses", type=int, default=20)

    def handle(self, *args, **opts) -> None:
        ptdir = Path(opts["dir"])
        if not ptdir.exists():
            self.stderr.write(f"Directory not found: {ptdir}")
            return

        files = sorted(p for p in ptdir.iterdir() if not p.name.startswith("."))
        total_rows = 0
        filled = {c: 0 for c in DERIVED}
        prov_by_field: dict[str, Counter] = {c: Counter() for c in DERIVED}
        per_file = []
        per_file_rates: list[dict[str, float]] = []  # each file's per-field fill rate
        miss_by_dim: dict[str, Counter] = {}

        for p in files:
            try:
                content = p.read_bytes()
                res = run_mapping(content, p.name, "")
            except Exception as exc:  # noqa: BLE001
                per_file.append((p.name, "ERR", 0, f"{type(exc).__name__}: {exc}"[:60]))
                continue
            rows = res["rows"]
            n = len(rows)
            total_rows += n
            f_here = {c: 0 for c in DERIVED}
            for r in rows:
                prov = r.get("provenance", {})
                for c in DERIVED:
                    if str(r["data"].get(c) or "").strip():
                        filled[c] += 1
                        f_here[c] += 1
                        prov_by_field[c][prov.get(c) or "?"] += 1
            for m in res["reviews"]:
                miss_by_dim.setdefault(m["dimension"], Counter())[m["raw"]] += m["occurrences"]
            # per-file: % of (rows × 9 fields) filled, plus per-field rates for averaging
            denom = n * len(DERIVED) or 1
            pct = round(100 * sum(f_here.values()) / denom)
            per_file.append((p.name, res["profile_code"], n, f"{pct}% filled"))
            if n:
                per_file_rates.append({c: f_here[c] / n for c in DERIVED})

        w = self.stdout.write
        w("=" * 78)
        w(f"{'FILE':<40} {'PROFILE':<18} {'ROWS':>5}  NOTE")
        w("-" * 78)
        for name, prof, n, note in per_file:
            w(f"{name[:40]:<40} {str(prof)[:18]:<18} {n:>5}  {note}")
        w("=" * 78)
        w(f"TOTAL ROWS: {total_rows}   FILES: {len(per_file_rates)}")
        nf = len(per_file_rates) or 1
        w("\nFILL RATE PER DERIVED FIELD  (row-weighted | file-averaged):")
        w("  (row-weighted follows the largest file; file-averaged weighs each brand equally)")
        for c in DERIVED:
            rw = round(100 * filled[c] / total_rows) if total_rows else 0
            fa = round(100 * sum(r[c] for r in per_file_rates) / nf)
            bar = "#" * (fa // 3)
            w(f"  {c:<16} {rw:>3}% | {fa:>3}%  {bar}")
        w("\nPROVENANCE OF FILLED CELLS  (direct/derived = trusted; alias/rule/inferred = glance):")
        for c in DERIVED:
            counts = prov_by_field[c]
            tot = sum(counts.values())
            if not tot:
                continue
            trusted = counts.get("direct", 0) + counts.get("derived", 0)
            parts = ", ".join(f"{src} {n}" for src, n in counts.most_common())
            w(f"  {c:<16} {round(100 * trusted / tot):>3}% trusted   [{parts}]")

        w("\nTOP UNRESOLVED RAW VALUES PER DIMENSION:")
        for dim in sorted(miss_by_dim):
            top = miss_by_dim[dim].most_common(opts["misses"])
            w(f"  [{dim}] {len(miss_by_dim[dim])} distinct")
            w("     " + " | ".join(f"{v!r}×{c}" for v, c in top))
