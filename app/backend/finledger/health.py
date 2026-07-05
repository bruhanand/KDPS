"""Books-health (equation-of-state / trial balance) read for the owner dashboard.

Surfaces the kernel's balanced-posting guarantee: every voucher fans into legs
that sum to zero, so the whole value GL's `Σ(amount)` (trial balance) is exactly
0 when the books tie. We also present the equation of state — assets the PT slice
builds (inventory + SOR stock + input GST + cash) against the liabilities/contra
it raises (vendor payable + GRNI + SOR contra). Finance/owner-only (ADR-0003).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.money import paise_to_rupees_str
from finledger.models import CashLedgerEntry, VendorLedgerEntry
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

        # F1 subledger-reconciliation proof: the single value GL is the book of
        # record, so its control accounts MUST equal the subledger running sums.
        # Vendor payable is credit-side (−paise) vs a +ve "we owe" subledger, so it
        # ties when Σ(vendor rows) == −GL payable. Cash is an asset (debit +), same
        # sign as its subledger.
        vendor_sub = VendorLedgerEntry.objects.aggregate(b=Sum("amount"))["b"] or 0
        cash_sub = CashLedgerEntry.objects.aggregate(b=Sum("amount"))["b"] or 0
        gl_payable = balances[GLAccount.VENDOR_PAYABLE]
        gl_cash = balances[GLAccount.CASH]
        vendor_reconciled = vendor_sub == -gl_payable
        cash_reconciled = cash_sub == gl_cash
        reconciliation = {
            "reconciled": vendor_reconciled and cash_reconciled,
            "vendor": {
                "reconciled": vendor_reconciled,
                "subledger_paise": vendor_sub,
                "subledger_rupees": paise_to_rupees_str(vendor_sub),
                "gl_control_paise": -gl_payable,
                "gl_control_rupees": paise_to_rupees_str(-gl_payable),
                "drift_paise": vendor_sub + gl_payable,
            },
            "cash": {
                "reconciled": cash_reconciled,
                "subledger_paise": cash_sub,
                "subledger_rupees": paise_to_rupees_str(cash_sub),
                "gl_control_paise": gl_cash,
                "gl_control_rupees": paise_to_rupees_str(gl_cash),
                "drift_paise": cash_sub - gl_cash,
            },
        }
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
                "reconciliation": reconciliation,
                "assets_paise": assets,
                "assets_rupees": paise_to_rupees_str(assets),
                "liabilities_paise": liabilities,
                "liabilities_rupees": paise_to_rupees_str(liabilities),
                "leg_count": GLEntry.objects.count(),
                "voucher_count": GLEntry.objects.values("doc_number").distinct().count(),
                "accounts": accounts,
            }
        )
