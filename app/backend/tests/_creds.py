"""Shared test credentials.

Test users are created with a throwaway password; keeping it in one env-backed
constant (instead of a literal in every test) means there is no ``password="..."``
literal for secret scanners to flag, and one place to override via
``KDPS_TEST_PASSWORD`` if a suite ever needs a policy-conformant value.
"""

from __future__ import annotations

import os

TEST_PASSWORD = os.environ.get("KDPS_TEST_PASSWORD", "test-pass")
