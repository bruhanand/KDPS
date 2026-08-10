"""Measure PT-mapper ACCURACY (not just fill rate) against a human-corrected golden CSV.

Re-runs the engine over the source brand files, joins to the golden rows by
(file, barcode), and reports per derived field:
  correct — engine value == golden value
  wrong   — both present but differ        (the dangerous case: a confident mis-map)
  missed  — golden has a value, engine blank
  over    — engine guessed a value, golden says it should be blank

    python manage.py ptmap_accuracy --golden goldenset_corrected.csv
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from ptmapper.engine import clean_code, norm, run_mapping
from ptmapper.profiles import CONTROLLED

FIELDS = list(CONTROLLED.keys())


class Command(BaseCommand):
    help = "Measure mapping accuracy against a human-corrected golden CSV."

    def add_arguments(self, parser: Any) -> None:
        repo = Path(settings.BASE_DIR).parent.parent
        default_dir = repo / "docs" / "data-from-kdps" / "Q&A-req-recieved" / "PT FILE"
        parser.add_argument("--golden", required=True)
        parser.add_argument("--dir", default=str(default_dir))

    def _load_golden(self, path: Path) -> dict[str, dict[str, dict[str, str]]]:
        golden: dict[str, dict[str, dict[str, str]]] = {}
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                fn = (row.get("file") or "").strip()
                bc = clean_code(row.get("barcode") or "")
                if not fn or not bc:
                    continue
                golden.setdefault(fn, {})[bc] = {
                    fld: (row.get(fld) or "").strip() for fld in FIELDS
                }
        return golden

    def handle(self, *args: Any, **opts: Any) -> None:
        gpath = Path(opts["golden"])
        if not gpath.exists():
            self.stderr.write(f"Golden file not found: {gpath}")
            return
        golden = self._load_golden(gpath)
        ptdir = Path(opts["dir"])
        stat: dict[str, Counter[str]] = {f: Counter() for f in FIELDS}
        matched = unmatched = 0

        for fn, bcmap in golden.items():
            src = ptdir / fn
            if not src.exists():
                self.stderr.write(f"skip (source missing): {fn}")
                continue
            try:
                res = run_mapping(src.read_bytes(), fn, "")
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"skip ({exc}): {fn}")
                continue
            eng = {clean_code(r["data"].get("BARCODE", "")): r["data"] for r in res["rows"]}
            for bc, exp in bcmap.items():
                d = eng.get(bc)
                if d is None:
                    unmatched += 1
                    continue
                matched += 1
                for fld in FIELDS:
                    e, g = norm(d.get(fld, "")), norm(exp.get(fld, ""))
                    if not e and not g:
                        continue
                    if e == g:
                        stat[fld]["correct"] += 1
                    elif g and e:
                        stat[fld]["wrong"] += 1
                    elif g:
                        stat[fld]["missed"] += 1
                    else:
                        stat[fld]["over"] += 1

        w = self.stdout.write
        w(f"golden rows matched by barcode: {matched}  (unmatched: {unmatched})")
        w(f"\n{'FIELD':<16} {'ACC%':>5}   correct / wrong / missed / over")
        w("-" * 56)
        tot_correct = tot_all = 0
        for fld in FIELDS:
            c = stat[fld]
            tot = c["correct"] + c["wrong"] + c["missed"] + c["over"]
            acc = round(100 * c["correct"] / tot) if tot else 0
            tot_correct += c["correct"]
            tot_all += tot
            flag = "  <-- mis-maps" if c["wrong"] else ""
            tally = f"{c['correct']} / {c['wrong']} / {c['missed']} / {c['over']}"
            w(f"  {fld:<14} {acc:>4}%   {tally}{flag}")
        overall = round(100 * tot_correct / tot_all) if tot_all else 0
        w("-" * 56)
        w(f"  {'OVERALL':<14} {overall:>4}%   ({tot_correct}/{tot_all} judged cells correct)")
