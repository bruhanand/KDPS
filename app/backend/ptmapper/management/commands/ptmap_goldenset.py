"""Export the engine's current guesses as a golden-set TEMPLATE for KDPS to correct.

Fill rate ("a value was assigned") is not accuracy ("the value is right"). To measure
accuracy we need ground truth. The cheapest way to get it: export what the engine
currently produces for a sample of rows, hand it to a merchandiser to **correct only
the wrong cells**, then feed the corrected file to `ptmap_accuracy`.

    python manage.py ptmap_goldenset --out goldenset_template.csv --sample 30
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from ptmapper.engine import run_mapping
from ptmapper.profiles import CONTROLLED

FIELDS = list(CONTROLLED.keys())  # the 9 derived fields to verify
HEADER = ["file", "barcode", "design", *FIELDS]


class Command(BaseCommand):
    help = "Export engine guesses as a golden-set template for human correction."

    def add_arguments(self, parser: Any) -> None:
        repo = Path(settings.BASE_DIR).parent.parent
        default_dir = repo / "docs" / "data-from-kdps" / "Q&A-req-recieved" / "PT FILE"
        parser.add_argument("--dir", default=str(default_dir))
        parser.add_argument("--out", default="goldenset_template.csv")
        parser.add_argument("--sample", type=int, default=30, help="rows per file")

    def handle(self, *args: Any, **opts: Any) -> None:
        ptdir = Path(opts["dir"])
        if not ptdir.exists():
            self.stderr.write(f"Directory not found: {ptdir}")
            return
        out_rows = []
        for p in sorted(x for x in ptdir.iterdir() if not x.name.startswith(".")):
            try:
                res = run_mapping(p.read_bytes(), p.name, "")
            except Exception:  # noqa: BLE001
                continue
            for r in res["rows"][: opts["sample"]]:
                d = r["data"]
                out_rows.append(
                    [
                        p.name,
                        d.get("BARCODE", ""),
                        d.get("DESIGN", ""),
                        *[d.get(f, "") for f in FIELDS],
                    ]
                )
        with open(opts["out"], "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(out_rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(out_rows)} rows × {len(FIELDS)} fields to {opts['out']}. "
                f"Correct the wrong cells, then: manage.py ptmap_accuracy --golden {opts['out']}"
            )
        )
