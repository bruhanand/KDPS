"""Model registration surface for the `core` kernel app.

Django discovers models by importing `<app>.models`. The kernel keeps its
primitives in focused modules (`ledger.py`, …); this re-exports the concrete
models so Django registers them and migrations are generated.
"""

from __future__ import annotations

from core.documents import DocumentProbe, VoucherSeries
from core.ledger import LedgerProbe

__all__ = ["DocumentProbe", "LedgerProbe", "VoucherSeries"]
