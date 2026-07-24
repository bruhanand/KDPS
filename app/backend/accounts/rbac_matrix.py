"""The SIDEBAR RBAC matrix, transcribed as the seed default (issue #85).

Source of truth: ``ERP_DASHBOARD_V1.xlsx`` → sheet "SIDEBAR RBAC" (24 Jul 2026),
the six-persona table locked with Anand. Each cell is the exact sheet wording;
the leading rung is the normalised capability (see ``sections`` for the ladder).

This module is only the **default** — ``seed_foundation`` writes it into each
``Role.section_access`` row, and the live API reads it back from the DB. So a
trained admin retunes access by editing a Role (data), never by shipping code
(Rule 12); this table just says where every fresh install starts.

Two ratified corrections to the client's original Sheet-1 matrix are baked in:
  · the store person gets receive-at-own-store + PT-making for direct receipts
    (Sheet 1 said NO on GRN; the booking-less direct-delivery decision wins);
  · Admin gets **no** Money access — Sheet-1 note (2), kept deliberately.

One section has **no sheet row at all**: ``staff``. The sheet predates KDPS's
hand-drawn store sidebar, which puts attendance in the store person's daily
screen (spec #84, user story 27), so #87 adds the section with derived access —
marked ``(derived)`` in the label so nobody mistakes it for the sheet. It is
data like every other cell: retune it on the Role row, no release.

That same sheetless section is where the two store roles part company. The sheet
has one "Store Person" persona covering both, but the sketch's "Member Details"
— add/remove people, bank details, monthly target vs achievement — is a store
*manager's* job, not a cashier's. ``ROLE_OVERRIDES`` carries that one divergence,
and it may only touch a sheetless section, so a persona's ratified cells stay
the sheet's word.

Scope words in the cells ("Own store", "Assigned brands", "All (network)") are
*display context only* — the acting scope is the separate ``scope_type``
dimension (ADR-0003), not the capability. They are preserved verbatim as the
label so the payload can show "why" a role sees what it sees.
"""

from __future__ import annotations

from accounts.sections import (
    CAP_APPROVE,
    CAP_MANAGE,
    CAP_NONE,
    CAP_OPERATE,
    CAP_VIEW,
    SECTION_CODES,
    is_valid_capability,
    is_valid_section,
)

# Persona code → { section_code: (capability, exact sheet label) }.
# A section absent for a persona is treated as CAP_NONE (fail-closed).
MATRIX: dict[str, dict[str, tuple[str, str]]] = {
    "owner": {
        "home": (CAP_VIEW, "All (network)"),
        "sell": (CAP_VIEW, "View"),
        "booking": (CAP_APPROVE, "Approve"),
        "receive_goods": (CAP_VIEW, "View all"),
        "transfer": (CAP_APPROVE, "Override"),
        "stock_count": (CAP_APPROVE, "View all + approve big variances"),
        "return_to_brand": (CAP_APPROVE, "Approve"),
        "stock": (CAP_MANAGE, "Full (all locations)"),
        "money": (CAP_MANAGE, "Full"),
        "offers_price": (CAP_APPROVE, "Approve / Override"),
        "staff": (CAP_MANAGE, "Full (derived)"),
        "reports": (CAP_VIEW, "All"),
        "setup": (CAP_MANAGE, "Full"),
    },
    "store_person": {
        "home": (CAP_VIEW, "Own store"),
        "sell": (CAP_OPERATE, "Create (bill, return, customer)"),
        "booking": (CAP_NONE, "No"),
        "receive_goods": (CAP_OPERATE, "Receive + PT (own store)"),
        "transfer": (CAP_OPERATE, "Request / Send / Receive"),
        "stock_count": (CAP_OPERATE, "Count own store"),
        "return_to_brand": (CAP_OPERATE, "Mark damage only"),
        "stock": (CAP_VIEW, "Own store"),
        "money": (CAP_OPERATE, "Expenses only (create)"),
        "offers_price": (CAP_VIEW, "View"),
        # The hand-drawn store sidebar puts biometric check-in in the daily
        # screen — so the store person *operates* Staff (own attendance), even
        # though employee records and payroll stay a back-office promise.
        "staff": (CAP_OPERATE, "Own attendance (derived)"),
        "reports": (CAP_VIEW, "Own store only"),
        "setup": (CAP_NONE, "No"),
    },
    "warehouse": {
        "home": (CAP_VIEW, "Warehouse"),
        "sell": (CAP_NONE, "No"),
        "booking": (CAP_OPERATE, "Draft"),
        "receive_goods": (CAP_OPERATE, "Create (GRN, PT)"),
        "transfer": (CAP_OPERATE, "Execute (distribute, dispatch)"),
        "stock_count": (CAP_OPERATE, "Count warehouse"),
        "return_to_brand": (CAP_OPERATE, "Create & execute"),
        "stock": (CAP_MANAGE, "Full"),
        "money": (CAP_OPERATE, "Expenses only (create)"),
        "offers_price": (CAP_VIEW, "View"),
        "staff": (CAP_OPERATE, "Own attendance (derived)"),
        "reports": (CAP_VIEW, "All"),
        "setup": (CAP_OPERATE, "Products only"),
    },
    "brand_manager": {
        "home": (CAP_VIEW, "Assigned brands"),
        "sell": (CAP_VIEW, "View"),
        "booking": (CAP_OPERATE, "Create"),
        "receive_goods": (CAP_VIEW, "View"),
        "transfer": (CAP_APPROVE, "Approve"),
        "stock_count": (CAP_VIEW, "View assigned brands"),
        "return_to_brand": (CAP_VIEW, "View own brands"),
        "stock": (CAP_VIEW, "Assigned brands"),
        "money": (CAP_NONE, "No"),
        "offers_price": (CAP_APPROVE, "Recommend + approve within limit"),
        # A brand manager's scope is brands, not people — no staff surface.
        "staff": (CAP_NONE, "No (derived)"),
        "reports": (CAP_VIEW, "Own brands only"),
        "setup": (CAP_OPERATE, "Edit assigned products"),
    },
    "accounts": {
        "home": (CAP_VIEW, "Finance view"),
        "sell": (CAP_VIEW, "View"),
        "booking": (CAP_VIEW, "View"),
        "receive_goods": (CAP_VIEW, "View"),
        "transfer": (CAP_VIEW, "View"),
        "stock_count": (CAP_VIEW, "View"),
        "return_to_brand": (CAP_VIEW, "View (credit notes)"),
        "stock": (CAP_VIEW, "View"),
        "money": (CAP_MANAGE, "Full"),
        "offers_price": (CAP_VIEW, "View"),
        # Payroll inputs and sales incentives are an Accounts read, not an edit.
        "staff": (CAP_VIEW, "View (payroll inputs) (derived)"),
        "reports": (CAP_VIEW, "All"),
        "setup": (CAP_VIEW, "View"),
    },
    "admin": {
        "home": (CAP_VIEW, "All"),
        "sell": (CAP_MANAGE, "All"),
        "booking": (CAP_MANAGE, "Configure"),
        "receive_goods": (CAP_MANAGE, "All"),
        "transfer": (CAP_VIEW, "Monitor"),
        "stock_count": (CAP_MANAGE, "All"),
        "return_to_brand": (CAP_MANAGE, "All"),
        "stock": (CAP_MANAGE, "Full"),
        "money": (CAP_NONE, "No"),
        "offers_price": (CAP_MANAGE, "Configure"),
        "staff": (CAP_MANAGE, "Full (derived)"),
        "reports": (CAP_VIEW, "All"),
        "setup": (CAP_MANAGE, "Full (incl. Users & Roles)"),
    },
}

# The six personas map onto the seeded role *codes*. "Store Person" covers both
# store roles; "Admin" is the it_admin role. Every canonical role must resolve
# to a persona so the contract test can assert it against the sheet.
ROLE_PERSONA = {
    "owner": "owner",
    "store_manager": "store_person",
    "store_staff": "store_person",
    "warehouse": "warehouse",
    "brand_manager": "brand_manager",
    "accounts": "accounts",
    "it_admin": "admin",
}

# Sections the SIDEBAR RBAC sheet never covered. Only these may be overridden
# per role code — everything else is the sheet's ratified word.
SHEETLESS_SECTIONS = frozenset({"staff"})

# Per-role-code cells layered *on top of* the persona row, for the case where two
# seeded roles share a persona but genuinely differ.
#
# ``store_manager`` and ``store_staff`` are both "Store Person" and hold the same
# twelve sheet cells. They differ once: the hand-drawn Store Ops screen puts
# "Member Details" — add/remove members, contact **and bank** details, monthly
# target vs achievement, growth/de-growth — in the store's own daily list
# (settled 25 Jul 2026: members are staff scorecards, not loyalty customers; the
# POS still owns the customer). Managing people is the manager's job, so the
# manager holds ``staff: manage`` while the cashier keeps ``operate`` — their own
# attendance and nothing else. Scope stays "own store" through the separate
# ``scope_type`` dimension (ADR-0003), never the capability.
ROLE_OVERRIDES: dict[str, dict[str, tuple[str, str]]] = {
    "store_manager": {
        "staff": (CAP_MANAGE, "Own store members + attendance (derived)"),
    },
}

# Roles that predate the sheet and have no persona row. They get sensible,
# clearly-derived access so seeded users aren't blank in the new contract — but
# these are NOT the RBAC matrix and can be retuned freely as data.
DERIVED_ACCESS: dict[str, dict[str, tuple[str, str]]] = {
    # HO Operations / Buyer — network operator, no money/setup ownership.
    "ho_ops": {
        "home": (CAP_VIEW, "All (network)"),
        "booking": (CAP_OPERATE, "Create"),
        "receive_goods": (CAP_VIEW, "View all"),
        "transfer": (CAP_APPROVE, "Approve"),
        "stock_count": (CAP_APPROVE, "Approve variances"),
        "return_to_brand": (CAP_VIEW, "View"),
        "stock": (CAP_VIEW, "All locations"),
        "offers_price": (CAP_OPERATE, "Plan"),
        "staff": (CAP_VIEW, "All (network)"),
        "reports": (CAP_VIEW, "All"),
    },
    # HO Data Steward — edits masters, reads stock. Setup stays at `operate`
    # (masters only): Users & Roles admin needs `setup: manage`, which only
    # Owner and Admin hold — a data steward must not gain that (issue #85 review).
    "data_steward": {
        "home": (CAP_VIEW, "All (network)"),
        "stock": (CAP_VIEW, "All locations"),
        "reports": (CAP_VIEW, "All"),
        "setup": (CAP_OPERATE, "Masters"),
    },
}


def section_access_for(role_code: str) -> dict[str, dict[str, str]]:
    """Full 13-section access map for a role, as stored in ``section_access``.

    Every section is present (missing → explicit ``none``), so the row is
    self-describing and fail-closed. Shape: ``{section: {capability, label}}``.
    """
    persona = ROLE_PERSONA.get(role_code)
    base = MATRIX.get(persona, {}) if persona else DERIVED_ACCESS.get(role_code, {})
    source = {**base, **ROLE_OVERRIDES.get(role_code, {})}
    out: dict[str, dict[str, str]] = {}
    for section in SECTION_CODES:
        capability, label = source.get(section, (CAP_NONE, "No"))
        out[section] = {"capability": capability, "label": label}
    return out


def _validate() -> None:
    """Guard the transcription: catch a typo'd section/capability at import.

    All three seed sources are checked so a slip in a ``DERIVED_ACCESS`` or
    ``ROLE_OVERRIDES`` cell fails loudly here rather than silently fail-closing
    that role's access. Only ``MATRIX`` must be complete (all 13 sections);
    derived and override rows are partial by design (absent → the persona's cell,
    else ``none``).
    """
    for source, cells_by_role in (
        ("matrix", MATRIX),
        ("derived", DERIVED_ACCESS),
        ("override", ROLE_OVERRIDES),
    ):
        for role, cells in cells_by_role.items():
            for section, (capability, _) in cells.items():
                assert is_valid_section(section), f"{source}/{role}: bad section {section!r}"
                assert is_valid_capability(capability), (
                    f"{source}/{role}: bad capability {capability!r}"
                )
    for persona, cells in MATRIX.items():
        missing = set(SECTION_CODES) - set(cells)
        assert not missing, f"{persona}: matrix missing sections {sorted(missing)}"
    # An override must never restate a ratified sheet cell — only the sections
    # the sheet left blank are ours to vary per role.
    for role, cells in ROLE_OVERRIDES.items():
        off_sheet = set(cells) - SHEETLESS_SECTIONS
        assert not off_sheet, (
            f"override/{role}: may not override sheet sections {sorted(off_sheet)}"
        )


_validate()
