"""Correction capture (Slice 1 of the self-improving mapper).

Every hand-edit that truly changes a cell becomes one durable, append-only
CorrectionEvent carrying before/after/actor/raw/provenance — the training signal
for mining and the Rule-10 audit trail. A rejected PATCH writes nothing; a re-map
that deletes the rows leaves the events (pt_row → NULL); an event never updates.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import User
from ptmapper.models import ControlledValue, CorrectionEvent, PtFile, PtRow


@pytest.fixture
def vocab(db):
    for dim, values in {
        "brand": ["PETER ENGLAND", "JOCKEY"],
        "gender": ["MALE", "FEMALE"],
        "color": ["BLUE", "RED"],
        "fit": ["SLIM", "REGULAR"],
        "size": ["M", "L"],
        "season": ["SPRING SUMMER(Jun-26)"],
        "gst": ["5", "12"],
        "sub_category": ["CASUAL WEAR"],
        "type": ["TOP WEAR"],
        "item": ["SHIRT"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="editor", password="x", full_name="Editor One")


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def pt_file(db):
    pt = PtFile.objects.create(original_filename="pe.xlsx", row_count=2)
    r1 = PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={"BRAND": "PETER ENGLAND", "GENDER": "", "FIT": "", "QTY": 2, "MRP": 100},
        blanks=["GENDER", "FIT"],
        provenance={"BRAND": "direct"},
        raw={"BRAND": "PE", "GENDER": "PJ RG OCTANEMIDSTR", "FIT": "PJ RG OCTANEMIDSTR"},
    )
    r2 = PtRow.objects.create(
        pt_file=pt,
        line_no=2,
        data={"BRAND": "PETER ENGLAND", "GENDER": "", "FIT": "", "QTY": 1, "MRP": 200},
        blanks=["GENDER", "FIT"],
        provenance={"BRAND": "direct"},
        raw={"BRAND": "PE", "GENDER": "PJ RG OCTANEMIDSTR", "FIT": "PJ RG OCTANEMIDSTR"},
    )
    return pt, r1, r2


# ---------------------------------------------------------------- capture


def test_one_event_per_changed_cell_captures_full_before_after(client, user, vocab, pt_file):
    pt, r1, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r1.id, "data": {"FIT": "REGULAR"}}]},
        format="json",
    )
    assert resp.status_code == 200
    events = list(CorrectionEvent.objects.all())
    assert len(events) == 1
    e = events[0]
    assert (e.column, e.dimension) == ("FIT", "fit")
    assert (e.old_value, e.new_value) == ("", "REGULAR")
    assert e.raw_value == "PJ RG OCTANEMIDSTR"  # from row.raw, not the displayed value
    assert e.provenance_before == ""  # FIT was blank before
    assert e.brand == "PETER ENGLAND"  # resolved BRAND = the mining scope key
    assert e.actor_id == user.id
    assert e.edit_kind == "cell"
    assert (e.file_name, e.line_no) == ("pe.xlsx", 1)
    assert (e.pt_row_id, e.pt_file_id) == (r1.id, pt.id)


def test_provenance_before_records_prior_source(client, vocab, pt_file):
    pt, _, r2 = pt_file
    # BRAND already carried provenance 'direct'; correcting it records that.
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r2.id, "data": {"BRAND": "JOCKEY"}}]},
        format="json",
    )
    assert resp.status_code == 200
    e = CorrectionEvent.objects.get()
    assert e.provenance_before == "direct"
    assert (e.old_value, e.new_value) == ("PETER ENGLAND", "JOCKEY")
    assert e.brand == "JOCKEY"  # scope follows the corrected brand (post-edit)


def test_same_value_save_records_no_event(client, vocab, pt_file):
    pt, _, r2 = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r2.id, "data": {"BRAND": "PETER ENGLAND"}}]},  # already that value
        format="json",
    )
    assert resp.status_code == 200
    assert CorrectionEvent.objects.count() == 0


def test_bulk_fill_makes_one_event_per_changed_row_with_scope_kind(client, vocab, pt_file):
    pt, _, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"fills": [{"column": "GENDER", "value": "MALE", "scope": "blank"}]},
        format="json",
    )
    assert resp.status_code == 200
    events = CorrectionEvent.objects.all()
    assert events.count() == 2  # both rows had GENDER blank
    assert {e.edit_kind for e in events} == {"fill_blank"}
    assert {e.line_no for e in events} == {1, 2}


def test_fill_match_raw_scope_kind_and_only_matching_rows(client, vocab, pt_file):
    pt, r1, r2 = pt_file
    # only r1/r2 share raw FIT 'PJ RG OCTANEMIDSTR'; fill both by match_raw
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {
            "fills": [
                {"column": "FIT", "value": "SLIM", "scope": {"match_raw": "PJ RG OCTANEMIDSTR"}}
            ]
        },  # noqa: E501
        format="json",
    )
    assert resp.status_code == 200
    events = CorrectionEvent.objects.all()
    assert events.count() == 2
    assert {e.edit_kind for e in events} == {"fill_match_raw"}


def test_rejected_patch_writes_zero_events(client, vocab, pt_file):
    pt, r1, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r1.id, "data": {"GENDER": "MENS", "FIT": "REGULAR"}}]},  # MENS invalid
        format="json",
    )
    assert resp.status_code == 400
    assert CorrectionEvent.objects.count() == 0  # all-or-nothing: no partial capture


# ---------------------------------------------------------------- durability


def test_rerun_keeps_events_after_rows_die(client, vocab):
    up = SimpleUploadedFile("bare.csv", b"BARCODE,QTY,MRP\nB1,2,100\n", content_type="text/csv")
    created = client.post(
        "/api/ptmapper/files", {"file": up, "brand": "JOCKEY"}, format="multipart"
    )
    assert created.status_code == 201, created.json()
    pt_id = created.json()["id"]
    row_id = created.json()["rows"][0]["id"]

    edit = client.patch(
        f"/api/ptmapper/files/{pt_id}/rows",
        {"rows": [{"id": row_id, "data": {"GENDER": "MALE"}}]},
        format="json",
    )
    assert edit.status_code == 200
    assert CorrectionEvent.objects.count() == 1

    rerun = client.post(f"/api/ptmapper/files/{pt_id}/rerun", {}, format="json")
    assert rerun.status_code == 200
    # rows were wiped + rebuilt — the event survives, pt_row nulled, pt_file kept
    assert CorrectionEvent.objects.count() == 1
    e = CorrectionEvent.objects.get()
    assert e.pt_row_id is None
    assert e.pt_file_id == pt_id


def test_correction_event_is_append_only(db):
    e = CorrectionEvent.objects.create(column="FIT", new_value="REGULAR")
    e.new_value = "SLIM"
    with pytest.raises(ValueError, match="append-only"):
        e.save()


# ---------------------------------------------------------------- serialisation


def test_row_detail_exposes_raw(client, vocab, pt_file):
    pt, r1, _ = pt_file
    resp = client.get(f"/api/ptmapper/files/{pt.id}")
    assert resp.status_code == 200
    row = next(r for r in resp.json()["rows"] if r["id"] == r1.id)
    assert row["raw"]["FIT"] == "PJ RG OCTANEMIDSTR"
