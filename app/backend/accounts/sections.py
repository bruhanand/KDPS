"""The canonical sidebar sections and the capability vocabulary (issue #85).

This is the *catalog* half of the RBAC contract — the fixed list of sections a
KDPS person can be granted, in sidebar order, and the ladder of capability
levels a role can hold on each. *Which* role gets *what* is data (see
``rbac_matrix`` and ``Role.section_access``, Rule 12 — no release to retune
access); the catalog itself is code because adding a section means shipping the
screens behind it.

The twelve sections are the SIDEBAR RBAC sheet
(``docs/data-from-kdps/scope-dashboard-detail/ERP_DASHBOARD_V1.xlsx`` →
"SIDEBAR RBAC", 24 Jul 2026). "Staff" from the 13-section design is deliberately
absent: it has no row in the RBAC matrix yet (parked pending KDPS's
staff-vs-customer answer), and this slice returns *exactly* the matrix.

These section codes are a new, parallel vocabulary to the legacy
``NAV_GROUPS`` (the five architecture layers). This ticket is contract-only —
the old groups still drive today's sidebar; the re-housing (#87) switches the
shell over to these sections and can then retire the layer names.
"""

from __future__ import annotations

# --- Capability ladder -----------------------------------------------------
# An ordinal ladder: a role holds one rung per section. Higher rungs include
# the powers of the lower ones (manage ⊃ approve ⊃ operate ⊃ view ⊃ none). The
# free-text RBAC cells ("Draft", "Override", "Monitor", "Expenses only", …)
# each normalise to one rung for gating; the exact sheet wording is preserved
# alongside as the human label, so nothing from the sheet is lost.
CAP_NONE = "none"  # section hidden; no access
CAP_VIEW = "view"  # read-only
CAP_OPERATE = "operate"  # create / do the day's work in the section
CAP_APPROVE = "approve"  # second-eye: approve or override others' work
CAP_MANAGE = "manage"  # full control / configure the section

CAPABILITY_ORDER = [CAP_NONE, CAP_VIEW, CAP_OPERATE, CAP_APPROVE, CAP_MANAGE]
CAPABILITY_RANK = {cap: rank for rank, cap in enumerate(CAPABILITY_ORDER)}


def is_valid_capability(cap: str) -> bool:
    return cap in CAPABILITY_RANK


def meets(held: str, minimum: str) -> bool:
    """Does capability ``held`` reach at least ``minimum`` on the ladder?"""
    return CAPABILITY_RANK.get(held, 0) >= CAPABILITY_RANK.get(minimum, 0)


# --- Section catalog -------------------------------------------------------
# (code, label) in sidebar order. Order is the list order.
SECTIONS: list[tuple[str, str]] = [
    ("home", "Home"),
    ("sell", "Sell"),
    ("booking", "Booking"),
    ("receive_goods", "Receive Goods"),
    ("transfer", "Transfer"),
    ("stock_count", "Stock Count"),
    ("return_to_brand", "Return to Brand"),
    ("stock", "Stock"),
    ("money", "Money"),
    ("offers_price", "Offers & Price"),
    ("reports", "Reports"),
    ("setup", "Setup"),
]

SECTION_CODES = [code for code, _ in SECTIONS]
SECTION_LABELS = dict(SECTIONS)


def is_valid_section(code: str) -> bool:
    return code in SECTION_LABELS
