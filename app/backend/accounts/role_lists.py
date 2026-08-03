"""The register of hand-kept role lists — every gate that is *not* the ladder (#94).

One gate: an API permission is a section plus a minimum capability, read from the
role's stored access (``accounts.permissions.require_section``). A hand-kept list
of role codes survives only where the ladder provably cannot express the rule —
and then the reason is written down here rather than left as a set literal in a
view module for the next reader to reverse-engineer.

Declaring one is the whole mechanism::

    PATNA_ROLES = declare_role_list(
        "ptmapper.post_pt",
        ("accounts", "owner", "it_admin"),
        reason="...why the ladder cannot say this...",
    )

The contract test reads ``REGISTERED_ROLE_LISTS`` and asserts two things: every
entry carries a reason, and no role-list constant anywhere in the backend was
written *without* coming through here. So "we kept a role list" is a recorded
decision, never an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleListException:
    """One gate that stayed a role list, and why the ladder could not take it."""

    #: ``app.gate`` — the module and the thing it guards, e.g. ``masters.writes``.
    name: str
    roles: frozenset[str]
    reason: str


#: Declaration order, which is also the order the contract test reports them in.
REGISTERED_ROLE_LISTS: dict[str, RoleListException] = {}


def declare_role_list(name: str, roles: tuple[str, ...], *, reason: str) -> frozenset[str]:
    """Register a hand-kept role list and hand back the set to gate with.

    The reason is mandatory and non-empty by construction: a list nobody could
    justify in a sentence is one that belongs on the ladder instead.
    """
    if not reason.strip():  # pragma: no cover - programmer error
        raise ValueError(f"{name}: a hand-kept role list needs a reason")
    if name in REGISTERED_ROLE_LISTS:  # pragma: no cover - programmer error
        raise ValueError(f"{name}: already declared")
    frozen = frozenset(roles)
    REGISTERED_ROLE_LISTS[name] = RoleListException(name=name, roles=frozen, reason=reason)
    return frozen


# Floor rule #4 is deliberately the one role list Setup cannot edit.  It stays
# in this registry so the existing contract requires the written reason.
ACCESS_ADMINISTRATORS = declare_role_list(
    "accounts.access_administrators_floor",
    ("owner", "it_admin"),
    reason=(
        "Changing users, roles or permission policy is itself the power to grant "
        "power. The ratified floor reserves proposals and second-person decisions "
        "to Owner or IT Admin; storing this list in editable policy would let that "
        "same policy configure the floor away."
    ),
)

HEAD_OFFICE_VALUE_ACTORS = declare_role_list(
    "accounts.head_office_value_actors_floor",
    ("accounts", "owner"),
    reason=(
        "PT inwarding and V-flip create or change brand liability. The ratified "
        "segregation-of-duties floor reserves those postings to Accounts or Owner; "
        "an editable actor policy may narrow this pair but cannot add another role."
    ),
)
