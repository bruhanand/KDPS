"""The value General Ledger (ADR-0006).

One immutable, append-only table of balanced postings. Every business event fans
out into ≥2 legs whose signed paise sum to zero, written ONLY by
`core.posting.post_entries`. `amount` is signed paise — a **debit is positive, a
credit negative** — so a single voucher's legs sum to 0 and the whole ledger's
trial balance is exactly `Σ(amount) = 0` (the books-tie checksum).

This is the *value* GL kept alongside (not replacing) the quantity-bearing stock
ledger and Tally (the statutory book). Dimensions are snapshotted onto each leg at
write time: the master is the editable present, the posting is the frozen past.
"""

from __future__ import annotations

from django.db import models

from core.ledger import LedgerEntry


class GLAccount:
    """The minimal chart of value accounts the inbound→PT→vendor slice posts to.

    Plain stable string codes (a full account master is a later slice). Sign
    convention is carried by the leg amount (dr +, cr −), not the account.
    """

    INVENTORY = "INVENTORY"            # owned stock value (asset)
    SOR_STOCK = "SOR_STOCK"            # brand-owned stock held on SOR/consignment (memo asset)
    SOR_CONTRA = "SOR_CONTRA"          # off-book contra for SOR/consignment stock
    VENDOR_PAYABLE = "VENDOR_PAYABLE"  # accounts payable to vendors (liability)
    GRNI = "GRNI"                      # goods received not invoiced (interim)
    INPUT_GST = "INPUT_GST"            # recoverable input GST (asset)
    CASH = "CASH"                      # cash / bank / UPI (asset)
    SUSPENSE = "SUSPENSE"              # balancing holding account


class GLEntry(LedgerEntry):
    """One leg of a balanced value posting (append-only general ledger).

    Inherits the append-only ORM guard + DB trigger from `LedgerEntry`; written only
    by `core.posting.post_entries`. `amount` (paise) is signed: debit +, credit −.
    """

    account = models.CharField(max_length=32, db_index=True)
    doc_type = models.CharField(max_length=16)
    doc_number = models.CharField(max_length=128, db_index=True)
    against_voucher = models.CharField(max_length=128, blank=True, default="")
    party_type = models.CharField(max_length=16, blank=True, default="")
    party_code = models.CharField(max_length=64, blank=True, default="")
    store = models.ForeignKey(
        "masters.Store", null=True, blank=True, on_delete=models.PROTECT,
        related_name="gl_entries",
    )
    gstin = models.ForeignKey(
        "masters.Gstin", null=True, blank=True, on_delete=models.PROTECT,
        related_name="gl_entries",
    )
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    line_no = models.IntegerField(default=0)
    memo = models.CharField(max_length=240, blank=True, default="")
    posted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "core_gl_entry"
        ordering = ["-created_at", "line_no"]

    def __str__(self) -> str:
        return f"{self.doc_number} · {self.account} {self.amount}"


def account_balance(account: str, **filters: object) -> int:
    """Net paise on an account = Σ(amount) (debits +, credits −)."""
    qs = GLEntry.objects.filter(account=account, **filters)
    return qs.aggregate(b=models.Sum("amount"))["b"] or 0


def trial_balance(**filters: object) -> int:
    """Whole-ledger checksum: Σ(amount) over every leg. MUST be 0 when the books
    tie (each posting is balanced, so their sum is balanced)."""
    qs = GLEntry.objects.filter(**filters) if filters else GLEntry.objects.all()
    return qs.aggregate(b=models.Sum("amount"))["b"] or 0
