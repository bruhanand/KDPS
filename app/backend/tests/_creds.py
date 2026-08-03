"""Shared test credentials.

Two constants, both env-backed, so no suite carries a ``password="..."`` literal
for a secret scanner to flag and there is one place to override each:

* ``TEST_PASSWORD`` — the throwaway password every *hermetic* suite creates its
  own users with. It never leaves the test database.
* ``SEED_OWNER_PASSWORD`` — the password ``seed_foundation`` gives the demo owner.
  Not a secret (it is printed in ``memory/test_credentials.md`` and on the alpha
  login screen), but the *live* suites all need the same answer, and when the seed
  password is changed for a deployment the suites must follow it via
  ``KDPS_SEED_OWNER_PASSWORD`` rather than being edited one by one.

This module is imported by ~20 suites and must stay in version control: it holds
no secret, only the two names that keep secrets out of the tests.
"""

from __future__ import annotations

import os

TEST_PASSWORD = os.environ.get("KDPS_TEST_PASSWORD", "test-pass")
SEED_OWNER_PASSWORD = os.environ.get("KDPS_SEED_OWNER_PASSWORD", "Owner@123")
