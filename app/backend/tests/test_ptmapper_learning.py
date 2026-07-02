"""Staged learning + the one Lookup write-path (Slice 3 of the self-improving mapper).

A review resolution and an operator's "remember this" tick both flow through
``learning`` — the sole runtime writer of ``Lookup``. Review resolutions promote at
once (the steward is the gate); remember-ticks stage a proposal that promotes when
the file is *sent* to Patna (D1), or immediately if it is already sent. A learned
rule seeds from the raw source value, never the displayed one. Approve is idempotent
and role-gated; reject writes nothing.
"""

from __future__ import annotations

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from ptmapper import learning
from ptmapper.engine import norm
from ptmapper.models import (
    ControlledValue,
    Lookup,
    LookupProposal,
    PtFile,
    PtRow,
    ReviewItem,
)


@pytest.fixture
def vocab(db):
    for dim, values in {
        "brand": ["PETER ENGLAND", "ZILU"],
        "color": ["BLUE", "GREY", "RED"],
        "fit": ["SLIM", "REGULAR"],
        "size": ["M", "L"],
        "season": ["SPRING SUMMER(Jun-26)"],
        "gender": ["MALE"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)


@pytest.fixture
def steward(db):
    role = Role.objects.create(code="data_steward", name="Data Steward")
    return User.objects.create_user(username="steward", password="x", role=role)


@pytest.fixture
def client(steward):
    c = APIClient()
    c.force_authenticate(steward)
    return c


@pytest.fixture
def pe_file(db):
    """A Peter England draft in MAPPING with a coded-fit raw the engine couldn't map."""
    pt = PtFile.objects.create(original_filename="pe.xlsx", row_count=1)
    row = PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={"BRAND": "PETER ENGLAND", "FIT": "", "QTY": 1, "MRP": 100},
        blanks=["FIT"],
        provenance={"BRAND": "direct"},
        raw={"BRAND": "PE", "FIT": "PJ RG OCTANE"},
    )
    return pt, row


# ---------------------------------------------------------------- review resolution


def test_review_resolution_promotes_and_records_actor(client, steward, vocab):
    item = ReviewItem.objects.create(
        dimension="color",
        raw_value="MISTY",
        occurrences=3,
        context={"brands": ["PETER ENGLAND"]},  # single brand → default brand scope (D4)
    )
    resp = client.post(
        f"/api/ptmapper/review/{item.id}/resolve", {"target_value": "BLUE"}, format="json"
    )
    assert resp.status_code == 200, resp.json()
    prop = LookupProposal.objects.get(dimension="color", source_key="MISTY")
    assert (prop.origin, prop.status) == ("review", "approved")
    assert prop.decided_by_id == steward.id and prop.applied_at is not None
    lk = Lookup.objects.get(dimension="color", source_key="MISTY")
    assert (lk.target_value, lk.brand) == ("BLUE", "PETER ENGLAND")  # scoped to the item's brand


def test_review_resolution_multi_brand_defaults_global(client, vocab):
    item = ReviewItem.objects.create(
        dimension="color", raw_value="MISTY", context={"brands": ["PETER ENGLAND", "ZILU"]}
    )
    client.post(f"/api/ptmapper/review/{item.id}/resolve", {"target_value": "BLUE"}, format="json")
    assert Lookup.objects.get(dimension="color", source_key="MISTY").brand == ""  # global


# ---------------------------------------------------------------- remember (D1 SENT gate)


def _remember_fit(client, pt, row, value="REGULAR"):
    return client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {
            "rows": [{"id": row.id, "data": {"FIT": value}}],
            "remember": [{"row_id": row.id, "column": "FIT"}],
        },
        format="json",
    )


def test_remember_on_mapping_file_stays_proposed_until_sent(client, steward, vocab, pe_file):
    pt, row = pe_file
    resp = _remember_fit(client, pt, row)
    assert resp.status_code == 200, resp.json()
    prop = LookupProposal.objects.get(origin="remember")
    assert prop.status == "proposed"  # not yet promoted — the file hasn't been sent
    assert not Lookup.objects.filter(dimension="fit", source_key="PJ RG OCTANE").exists()

    # sending to Patna is the trust gate → the proposal promotes, actor = the ticker
    send = client.post(f"/api/ptmapper/files/{pt.id}/send", {}, format="json")
    assert send.status_code == 200, send.json()
    prop.refresh_from_db()
    assert prop.status == "approved" and prop.decided_by_id == steward.id
    lk = Lookup.objects.get(dimension="fit", source_key="PJ RG OCTANE")
    assert (lk.target_value, lk.brand) == ("REGULAR", "PETER ENGLAND")


def test_rule_seeds_from_raw_not_the_displayed_value(client, vocab, pe_file):
    pt, row = pe_file
    _remember_fit(client, pt, row, value="REGULAR")
    prop = LookupProposal.objects.get(origin="remember")
    # source_key is the raw the engine read, not the mapped value the operator sees
    assert prop.source_key == "PJ RG OCTANE"
    assert prop.target_value == "REGULAR"
    assert prop.brand == "PETER ENGLAND"


def test_remember_on_already_sent_file_promotes_immediately(client, vocab, pe_file):
    pt, row = pe_file
    pt.draft_stage = PtFile.DraftStage.SENT  # already sent
    pt.save(update_fields=["draft_stage"])
    resp = _remember_fit(client, pt, row)
    assert resp.status_code == 200, resp.json()
    prop = LookupProposal.objects.get(origin="remember")
    assert prop.status == "approved"  # instant, no send needed
    assert Lookup.objects.filter(dimension="fit", source_key="PJ RG OCTANE").exists()


def test_remember_dedupes_open_proposals(client, vocab, pe_file):
    pt, row = pe_file
    _remember_fit(client, pt, row, value="REGULAR")
    _remember_fit(client, pt, row, value="SLIM")  # same (dim, key, brand) → one open proposal
    props = LookupProposal.objects.filter(origin="remember", status="proposed")
    assert props.count() == 1
    assert props.get().target_value == "SLIM"  # latest value wins on the open proposal


def test_remember_rawless_or_uncontrolled_is_a_clean_error(client, vocab, pe_file):
    pt, row = pe_file
    # BARCODE isn't a learnable dimension → clean 400, nothing written
    bad_col = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"remember": [{"row_id": row.id, "column": "BARCODE"}]},
        format="json",
    )
    assert bad_col.status_code == 400
    # COLOR has no raw source value on this row → clean 400
    bad_raw = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {
            "rows": [{"id": row.id, "data": {"COLOR": "BLUE"}}],
            "remember": [{"row_id": row.id, "column": "COLOR"}],
        },
        format="json",
    )
    assert bad_raw.status_code == 400
    assert LookupProposal.objects.count() == 0
    assert not Lookup.objects.exists()


# ---------------------------------------------------------------- proposal decisions


def test_approve_is_idempotent_and_role_gated(client, steward, vocab):
    prop = LookupProposal.objects.create(
        dimension="color", source_key="MISTY", target_value="BLUE", brand="", origin="mined"
    )
    # a non-steward can't decide
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="nobody", password="x"))
    denied = plain.post(f"/api/ptmapper/proposals/{prop.id}/decide", {"action": "approve"})
    assert denied.status_code == 403

    url = f"/api/ptmapper/proposals/{prop.id}/decide"
    first = client.post(url, {"action": "approve"}, format="json")
    assert first.status_code == 200 and first.json()["status"] == "approved"
    second = client.post(url, {"action": "approve"}, format="json")
    assert second.status_code == 200  # idempotent
    assert Lookup.objects.filter(dimension="color", source_key="MISTY").count() == 1


def test_reject_writes_no_lookup(client, vocab):
    prop = LookupProposal.objects.create(
        dimension="color", source_key="MISTY", target_value="BLUE", brand="", origin="mined"
    )
    resp = client.post(
        f"/api/ptmapper/proposals/{prop.id}/decide", {"action": "reject"}, format="json"
    )
    assert resp.status_code == 200 and resp.json()["status"] == "rejected"
    assert not Lookup.objects.filter(dimension="color", source_key="MISTY").exists()


def test_proposals_list_filters_by_status(client, vocab):
    LookupProposal.objects.create(
        dimension="color", source_key="A", target_value="BLUE", origin="mined"
    )
    LookupProposal.objects.create(
        dimension="color", source_key="B", target_value="RED", origin="mined", status="approved"
    )
    open_only = client.get("/api/ptmapper/proposals").json()
    assert {p["source_key"] for p in open_only} == {"A"}
    every = client.get("/api/ptmapper/proposals?status=all").json()
    assert {p["source_key"] for p in every} == {"A", "B"}


# ---------------------------------------------------------------- shadow-check brand scope


def _sent_manual_row(brand: str, raw: str, confirmed: str) -> None:
    pt = PtFile.objects.create(
        original_filename=f"{brand}.xlsx", row_count=1, sent_at=timezone.now()
    )
    PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={"BRAND": brand, "COLOR": confirmed},
        provenance={"COLOR": "manual"},
        raw={"COLOR": raw},
    )


def test_shadow_check_ignores_another_brands_sent_manual_cell(vocab):
    """A brand-scoped promotion must not be auto-rejected by a *different* brand's
    human-confirmed cell — the row conflict is scoped like the correction conflict."""
    _sent_manual_row("ZILU", "MISTY", "GREY")  # ZILU confirmed MISTY→GREY
    res = learning.shadow_check("color", norm("MISTY"), "BLUE", brand="PETER ENGLAND")
    assert res["ok"] is True  # PE's own rule is unblocked


def test_shadow_check_blocks_the_same_brands_sent_manual_cell(vocab):
    _sent_manual_row("PETER ENGLAND", "MISTY", "GREY")
    res = learning.shadow_check("color", norm("MISTY"), "BLUE", brand="PETER ENGLAND")
    assert res["ok"] is False
    assert any(c["kind"] == "manual_cell_conflict" for c in res["conflicts"])


def test_shadow_check_global_proposal_still_sees_every_manual_cell(vocab):
    """A global rule flips cells of all brands, so it must respect any brand's cell."""
    _sent_manual_row("ZILU", "MISTY", "GREY")
    res = learning.shadow_check("color", norm("MISTY"), "BLUE", brand="")
    assert res["ok"] is False
    assert any(c["kind"] == "manual_cell_conflict" for c in res["conflicts"])
