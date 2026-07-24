"""The canonical sidebar sections and the capability vocabulary (issue #85).

This is the *catalog* half of the RBAC contract — the fixed list of sections a
KDPS person can be granted, in sidebar order, and the ladder of capability
levels a role can hold on each. *Which* role gets *what* is data (see
``rbac_matrix`` and ``Role.section_access``, Rule 12 — no release to retune
access); the catalog itself is code because adding a section means shipping the
screens behind it.

Twelve of the thirteen sections are the SIDEBAR RBAC sheet
(``docs/data-from-kdps/scope-dashboard-detail/ERP_DASHBOARD_V1.xlsx`` →
"SIDEBAR RBAC", 24 Jul 2026). ``staff`` is the thirteenth: it has no row in that
sheet, but spec #84 puts Staff → Attendance in the store person's daily sidebar,
so #87 adds it with clearly-derived access (see ``rbac_matrix``). Members stays
parked pending KDPS's staff-vs-customer answer — the section exists, that
subsection is only a planned page.

These section codes replaced the legacy ``NAV_GROUPS`` (the five architecture
layers) as the shell's authority in #87: the sidebar, the client route guards
and the server-side section gate all read this vocabulary. ``NAV_GROUPS``
survives only as a legacy field on ``Role`` that nothing navigates by.
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
    ("staff", "Staff"),
    ("reports", "Reports"),
    ("setup", "Setup"),
]

SECTION_CODES = [code for code, _ in SECTIONS]
SECTION_LABELS = dict(SECTIONS)


def is_valid_section(code: str) -> bool:
    return code in SECTION_LABELS
