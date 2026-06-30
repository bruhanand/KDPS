"""Books-health (equation-of-state / trial balance) read for the owner dashboard.

Surfaces the kernel's balanced-posting guarantee: every voucher fans into legs
that sum to zero, so the whole value GL's `Σ(amount)` (trial balance) is exactly
0 when the books tie. We also present the equation of state — assets the PT slice
builds (inventory + SOR stock + input GST + cash) against the liabilities/contra
it raises (vendor payable + GRNI + SOR contra). Finance/owner-only (ADR-0003).
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.money import paise_to_rupees_str
from finledger.views import IsFinance

ACCOUNTS = [
    (GLAccount.INVENTORY, "Inventory (owned stock)", "asset"),
    (GLAccount.SOR_STOCK, "SOR / consignment stock", "asset"),
    (GLAccount.INPUT_GST, "Input GST", "asset"),
    (GLAccount.CASH, "Cash & bank", "asset"),
    (GLAccount.VENDOR_PAYABLE, "Vendor payable", "liability"),
    (GLAccount.GRNI, "Goods received, not invoiced", "liability"),
    (GLAccount.SOR_CONTRA, "SOR contra (off-book)", "liability"),
    (GLAccount.SUSPENSE, "Suspense", "liability"),
]


class BooksHealthView(APIView):
    """`GET /api/finledger/health` — trial balance + equation-of-state snapshot."""

    permission_classes = [IsAuthenticated, IsFinance]

    def get(self, request: Request) -> Response:
        balances = {code: account_balance(code) for code, _, _ in ACCOUNTS}
        tb = trial_balance()
        assets = sum(balances[c] for c, _, side in ACCOUNTS if side == "asset")
        # liabilities/contra are credit-side (negative paise); present magnitude.
        liabilities = -sum(balances[c] for c, _, side in ACCOUNTS if side == "liability")
        accounts: list[dict[str, Any]] = [
            {
                "code": code,
                "label": label,
                "side": side,
                "balance_paise": balances[code],
                "balance_rupees": paise_to_rupees_str(balances[code]),
            }
            for code, label, side in ACCOUNTS
        ]
        return Response(
            {
                "balanced": tb == 0,
                "trial_balance_paise": tb,
                "trial_balance_rupees": paise_to_rupees_str(tb),
                "assets_paise": assets,
                "assets_rupees": paise_to_rupees_str(assets),
                "liabilities_paise": liabilities,
                "liabilities_rupees": paise_to_rupees_str(liabilities),
                "leg_count": GLEntry.objects.count(),
                "voucher_count": GLEntry.objects.values("doc_number").distinct().count(),
                "accounts": accounts,
            }
        )
