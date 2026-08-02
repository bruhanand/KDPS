"""The manager's counter PIN: who may hold one, and how it is hashed (#182).

A store manager authorises an over-cap discount, or an unrecognised credit note,
by typing a PIN at the till - and the till is offline while they do it. So the
PIN is verified **on the device**, against a hash that came down in the dataset
(`sell.services.dataset._managers`), and every property below follows from that
one sentence.

**It is hashed with PBKDF2-SHA256 explicitly, not with the project's default
hasher.** `PASSWORD_HASHERS` puts bcrypt first, which is the right choice for a
password checked on a server; it is the wrong choice for a secret verified in a
browser, because the Web Crypto API a browser gives us has PBKDF2 and does not
have bcrypt. Verifying a bcrypt hash offline would mean shipping a bcrypt
implementation to the shop floor, and a hash nothing can verify is not a
credential. `till/pin.ts` reads the iteration count out of the string, so raising
it here needs nothing on the device.

**Not everybody may hold one.** The hash leaves the building on a shop-floor
device, so the only people whose hashes are ever written are the people a counter
could actually be asked to trust: somebody whose boundary is stores at all, who
holds `sell >= approve` on the stored matrix, and who is not the break-glass
superuser. That is the same sentence the dataset's manager list is built from,
and it is written here once so the two cannot drift.

**Nobody sets somebody else's.** The endpoint is self-service and asks for the
person's own password, because an override's whole value is that it names who
stood at the counter - and an administrator who could set a manager's PIN could
authorise a discount in that manager's name.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.hashers import PBKDF2PasswordHasher

from accounts.models import ScopeType
from accounts.permissions import user_can
from accounts.sections import CAP_APPROVE

#: Scopes whose boundary genuinely *is* a set of stores. A network- or
#: entity-wide administrator whose matrix cell happens to say `sell: manage` is
#: not one of a counter's people, and shipping their hash to fifty tills would be
#: a worse answer than shipping nobody's.
STORE_BOUND_SCOPES = (ScopeType.STORE, ScopeType.STORE_GROUP, ScopeType.REGION)

#: Four to six digits, the length a person can type on a counter keypad with a
#: customer waiting. Short by design and therefore weak by design: the protection
#: is that a PIN only ever authorises an exception that is recorded, on a device
#: that already holds the store's whole price list.
PIN_MIN_LENGTH = 4
PIN_MAX_LENGTH = 6

_hasher = PBKDF2PasswordHasher()


def hash_till_pin(pin: str) -> str:
    """A PIN as the till will read it: `pbkdf2_sha256$<iterations>$<salt>$<b64>`."""
    return _hasher.encode(pin, _hasher.salt())


def pin_problem(pin: str) -> str:
    """Why this is not a PIN, in a sentence for the person typing it - or ""."""
    if not pin.isdigit():
        return "A counter PIN is digits only - it is typed at a till, often on a keypad."
    if not PIN_MIN_LENGTH <= len(pin) <= PIN_MAX_LENGTH:
        return f"A counter PIN is {PIN_MIN_LENGTH} to {PIN_MAX_LENGTH} digits."
    if len(set(pin)) == 1:
        return "That PIN is the same digit repeated. Anybody watching would have it."
    return ""


def may_hold_till_pin(user: Any) -> bool:
    """Is this somebody a counter could be asked to trust? See the module docstring."""
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and not user.is_superuser
        and user.scope_type in STORE_BOUND_SCOPES
        and user_can(user, "sell", CAP_APPROVE)
    )
