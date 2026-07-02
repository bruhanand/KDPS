"""pg_trgm pre-fill suggestions (Slice 7 — deterministic, no LLM).

The /suggest endpoint pre-fills a dropdown for a raw value: exact Lookup hits
(brand-scoped before global) rank above Master values by trigram similarity.
Suggestions are Master vocabulary only, an exact lookup outranks a fuzzy match,
and the call writes nothing (Rule 8: it only pre-fills; a human still commits).
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from ptmapper.models import ControlledValue, Lookup, LookupProposal


@pytest.fixture
def vocab(db):
    for dim, values in {
        "color": ["BLUE", "NAVY", "GREY", "GREEN"],
        "brand": ["PETER ENGLAND"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)


@pytest.fixture
def client(db):
    c = APIClient()
    c.force_authenticate(User.objects.create_user(username="u", password="x"))
    return c


def test_exact_lookup_outranks_fuzzy(client, vocab):
    # 'GREYISH' fuzzes toward GREY, but a brand lookup maps it to BLUE — the lookup wins
    Lookup.objects.create(
        dimension="color", source_key="GREYISH", target_value="BLUE", brand="PETER ENGLAND"
    )
    resp = client.get("/api/ptmapper/suggest?dimension=color&q=GREYISH&brand=PETER ENGLAND")
    assert resp.status_code == 200
    sugg = resp.json()["suggestions"]
    assert sugg[0] == {"value": "BLUE", "reason": "lookup", "score": 1.0}


def test_suggestions_are_master_values_only(client, vocab):
    resp = client.get("/api/ptmapper/suggest?dimension=color&q=GREYISH")
    values = [s["value"] for s in resp.json()["suggestions"]]
    assert values  # a fuzzy hit exists
    master = set(ControlledValue.objects.filter(dimension="color").values_list("value", flat=True))
    assert all(v in master for v in values)  # never free text — only Master values
    assert "GREY" in values  # the obvious near-match surfaces


def test_brand_lookup_beats_global_lookup(client, vocab):
    Lookup.objects.create(dimension="color", source_key="MISTY", target_value="GREY", brand="")
    Lookup.objects.create(
        dimension="color", source_key="MISTY", target_value="NAVY", brand="PETER ENGLAND"
    )
    resp = client.get("/api/ptmapper/suggest?dimension=color&q=MISTY&brand=PETER ENGLAND")
    assert resp.json()["suggestions"][0]["value"] == "NAVY"  # brand-scoped first


def test_suggest_is_side_effect_free(client, vocab):
    def counts():
        return (
            Lookup.objects.count(),
            LookupProposal.objects.count(),
            ControlledValue.objects.count(),
        )

    before = counts()
    client.get("/api/ptmapper/suggest?dimension=color&q=BLUEISH")
    assert counts() == before  # pure read — pre-fills only, never commits


def test_blank_query_returns_nothing(client, vocab):
    assert client.get("/api/ptmapper/suggest?dimension=color&q=").json()["suggestions"] == []
