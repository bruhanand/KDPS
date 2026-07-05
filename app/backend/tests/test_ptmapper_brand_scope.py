"""Brand-scoped Lookup rules + resolver specificity (Slice 2 of the self-improving
mapper).

A brand-scoped rule (``Lookup.brand`` = a Master brand) beats a conflicting global
one and never fires for another brand; a global rule still resolves when no brand
row exists. Scope follows the row's *resolved* BRAND, so a multi-brand file maps
each row independently. The review-resolve call site passes ``brand`` explicitly,
so seed + review can share the one global row (and coexist with a brand row)
without ``MultipleObjectsReturned``.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from rest_framework.test import APIClient

from accounts.models import Role, User
from ptmapper.engine import Resolver, map_record
from ptmapper.models import ControlledValue, Lookup, ReviewItem
from ptmapper.processing import _sync_review_items

GENERIC = {"code": "generic", "overrides": {}, "flags": {}}


@pytest.fixture
def vocab(db):
    for dim, values in {
        "brand": ["PETER ENGLAND", "ZILU"],
        "color": ["BLUE", "GREY", "RED"],
        "size": ["M", "L"],
        "fit": ["SLIM", "REGULAR"],
        "season": ["SPRING SUMMER(Jun-26)"],
        "gender": ["MALE"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)


# ---------------------------------------------------------------- resolver specificity


def test_brand_row_beats_conflicting_global_row(vocab):
    Lookup.objects.create(dimension="color", source_key="MISTY", target_value="GREY", brand="")
    Lookup.objects.create(
        dimension="color", source_key="MISTY", target_value="BLUE", brand="PETER ENGLAND"
    )
    r = Resolver()
    assert r.color("MISTY", brand="PETER ENGLAND") == ("BLUE", "alias")  # brand wins
    assert r.color("MISTY", brand="ZILU") == ("GREY", "alias")  # no ZILU row → global
    assert r.color("MISTY", brand="") == ("GREY", "alias")  # unscoped → global


def test_brand_row_never_fires_for_another_brand(vocab):
    Lookup.objects.create(
        dimension="fit", source_key="XZ", target_value="SLIM", brand="PETER ENGLAND"
    )
    r = Resolver()
    assert r.fit("XZ", brand="PETER ENGLAND") == ("SLIM", "alias")
    # another brand: no global fallback → a miss (recorded for the review queue)
    assert r.fit("XZ", brand="ZILU") == (None, "")
    assert "fit|XZ" in r.misses


def test_global_resolves_when_no_brand_row(vocab):
    Lookup.objects.create(dimension="size", source_key="SM", target_value="M", brand="")
    r = Resolver()
    assert r.size("SM", brand="PETER ENGLAND") == ("M", "alias")  # falls through to global
    assert r.size("SM", brand="") == ("M", "alias")


def test_coded_fit_prefers_brand_scoped_alias(vocab):
    # a Peter England coded fit-token learned per-brand; ZILU must not inherit it
    Lookup.objects.create(
        dimension="fit", source_key="OCTANE", target_value="SLIM", brand="PETER ENGLAND"
    )
    cands = ["PJ RG OCTANE", "RG", "OCTANE"]
    assert Resolver().fit("PJ RG OCTANE", candidates=cands, brand="PETER ENGLAND")[0] == "SLIM"
    assert Resolver().fit("PJ RG OCTANE", candidates=cands, brand="ZILU") == (None, "")


# ---------------------------------------------------------------- scope from resolved BRAND


def test_map_record_scopes_color_to_the_rows_brand(vocab):
    Lookup.objects.create(
        dimension="color", source_key="MISTY", target_value="BLUE", brand="PETER ENGLAND"
    )
    r = Resolver()
    pe = {"BARCODE": "B1", "QTY": 1, "MRP": 100, "BRAND": "PETER ENGLAND", "COLOR": "MISTY"}
    row_pe, _, prov_pe, _ = map_record(pe, GENERIC, r, "")
    assert (row_pe["COLOR"], prov_pe["COLOR"]) == ("BLUE", "alias")
    zl = {"BARCODE": "B2", "QTY": 1, "MRP": 100, "BRAND": "ZILU", "COLOR": "MISTY"}
    row_zl, _, prov_zl, _ = map_record(zl, GENERIC, r, "")
    assert row_zl["COLOR"] == ""  # the PE rule must not leak to ZILU
    # and the miss carries the resolved brand so a review can default to ZILU scope
    assert r.misses["color|MISTY"]["brands"] == ["ZILU"]


# ---------------------------------------------------------------- call-site safety


@pytest.fixture
def steward_client(vocab):
    role = Role.objects.create(code="data_steward", name="Data Steward")
    user = User.objects.create_user(username="steward", password=TEST_PASSWORD)
    user.role = role
    user.save()
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_seed_and_review_share_one_global_row(steward_client):
    # a seeded global row + a coexisting brand row for the same (dim, key)
    Lookup.objects.create(dimension="color", source_key="MISTY", target_value="RED", brand="")
    Lookup.objects.create(
        dimension="color", source_key="MISTY", target_value="BLUE", brand="PETER ENGLAND"
    )
    item = ReviewItem.objects.create(dimension="color", raw_value="MISTY", occurrences=2)
    resp = steward_client.post(
        f"/api/ptmapper/review/{item.id}/resolve", {"target_value": "GREY"}, format="json"
    )
    # no MultipleObjectsReturned: the brand='' identity found the one global row
    assert resp.status_code == 200, resp.json()
    globals_ = Lookup.objects.filter(dimension="color", source_key="MISTY", brand="")
    assert globals_.count() == 1  # updated in place, not duplicated
    assert globals_.get().target_value == "GREY"  # RED → GREY
    brand_row = Lookup.objects.get(dimension="color", source_key="MISTY", brand="PETER ENGLAND")
    assert brand_row.target_value == "BLUE"  # brand row untouched


# ---------------------------------------------------------------- cross-brand re-open (D4)


def test_resolved_item_reopens_for_another_brands_fresh_miss(vocab):
    """A brand-scoped resolution must not swallow the same raw when a *different*
    brand still misses it — the engine only reports a miss when neither a brand nor a
    global lookup fired, so a miss on a RESOLVED item means the resolution was scoped
    and doesn't cover this brand → the item re-opens, re-scoped to the missing brand."""
    item = ReviewItem.objects.create(
        dimension="color",
        raw_value="MISTY",
        status=ReviewItem.Status.RESOLVED,  # already resolved for Peter England (scoped)
        resolved_value="BLUE",
        occurrences=1,
        context={"brands": ["PETER ENGLAND"]},
    )
    miss = {
        "dimension": "color",
        "raw": "MISTY",
        "occurrences": 2,
        "samples": [],
        "brands": ["ZILU"],
    }  # noqa: E501
    open_count = _sync_review_items([miss])
    item.refresh_from_db()
    assert item.status == ReviewItem.Status.OPEN  # re-opened for ZILU
    assert item.context["brands"] == ["ZILU"]  # re-scoped to the brand that still misses
    assert item.resolved_value == ""  # the stale PE resolution is cleared
    assert open_count == 1  # the ZILU miss surfaces in the queue


def test_ignored_item_stays_ignored_across_remaps(vocab):
    """A steward's decision that a raw is noise must survive every re-map."""
    item = ReviewItem.objects.create(
        dimension="color",
        raw_value="NOISE",
        status=ReviewItem.Status.IGNORED,
        occurrences=1,
    )
    miss = {
        "dimension": "color",
        "raw": "NOISE",
        "occurrences": 5,
        "samples": [],
        "brands": ["ZILU"],
    }  # noqa: E501
    open_count = _sync_review_items([miss])
    item.refresh_from_db()
    assert item.status == ReviewItem.Status.IGNORED
    assert open_count == 0
