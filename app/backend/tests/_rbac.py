"""One way to build a Role in a test, so no suite has to remember the ritual.

Every gate resolves from ``Role.section_access`` (the SIDEBAR RBAC contract,
#85), and that column defaults to ``{}``. A role built without it therefore
reaches *nothing* — which is the correct fail-closed answer, and the worst
possible thing to debug: the suite fails with a 403 that reads like a defect in
the gate rather than a gap in the fixture. Nine test modules were each spelling
out ``section_access=section_access_for(code)`` by hand, and #94 had to go and
add it to six of them.

So: build the row the way ``seed_foundation`` builds it, in one place.
"""

from __future__ import annotations

from typing import Any

from accounts.models import Role
from accounts.rbac_matrix import section_access_for


def make_role(code: str, name: str | None = None, **extra: Any) -> Role:
    """A role seeded as ``seed_foundation`` seeds it — the matrix's access for
    ``code``.

    Reused if the test has already made one, since several suites build the same
    role from more than one place and the code is unique.
    """
    role, _ = Role.objects.get_or_create(
        code=code,
        defaults={"name": name or code, "section_access": section_access_for(code), **extra},
    )
    return role
