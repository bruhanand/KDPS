"""Preserve-manual re-run + widened repropagation (Slice 5, D2).

A re-map preserves hand-edited cells by default (re-applied by line_no after the
rebuild); an explicit ``discard_edits`` is the full wipe. A newly-approved rule
repropagates to *every* mapping-stage draft — filling blanks on hand-edited drafts
without ever clobbering a manual cell (the no-clobber invariant). Sent/posted files
are frozen and never re-mapped. Cells whose row vanished are reported, never lost.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from ptmapper.models import ControlledValue, LookupProposal, PtFile, PtRow
from ptmapper.processing import _reapply_manual


@pytest.fixture
def vocab(db):
    for dim, values in {
        "brand": ["PETER ENGLAND"],
        "color": ["BLUE", "RED"],
        "fit": ["SLIM", "REGULAR"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)


@pytest.fixture
def client(db):
    c = APIClient()
    c.force_authenticate(User.objects.create_user(username="wh", password=TEST_PASSWORD))
    return c


@pytest.fixture
def steward_client(db):
    role = Role.objects.create(code="data_steward", name="Data Steward")
    c = APIClient()
    c.force_authenticate(
        User.objects.create_user(username="steward", password=TEST_PASSWORD, role=role)
    )
    return c


def _upload(client, vocab, body):
    up = SimpleUploadedFile("f.csv", body, content_type="text/csv")
    r = client.post(
        "/api/ptmapper/files", {"file": up, "brand": "PETER ENGLAND"}, format="multipart"
    )
    assert r.status_code == 201, r.json()
    return r.json()["id"], r.json()["rows"][0]["id"]


# ---------------------------------------------------------------- preserve / discard


def test_rerun_preserves_manual_cells_and_keeps_the_flag(client, vocab):
    pt_id, row_id = _upload(client, vocab, b"BARCODE,QTY,MRP\nB1,2,100\n")
    client.patch(
        f"/api/ptmapper/files/{pt_id}/rows",
        {"rows": [{"id": row_id, "data": {"FIT": "SLIM"}}]},
        format="json",
    )
    rerun = client.post(f"/api/ptmapper/files/{pt_id}/rerun", {}, format="json")
    assert rerun.status_code == 200
    row = rerun.json()["rows"][0]
    assert row["data"]["FIT"] == "SLIM"  # manual cell survived the re-map
    assert row["provenance"]["FIT"] == "manual"
    assert rerun.json()["manually_edited"] is True


def test_discard_edits_resets_to_the_engine_mapping(client, vocab):
    pt_id, row_id = _upload(client, vocab, b"BARCODE,QTY,MRP\nB1,2,100\n")
    client.patch(
        f"/api/ptmapper/files/{pt_id}/rows",
        {"rows": [{"id": row_id, "data": {"FIT": "SLIM"}}]},
        format="json",
    )
    rerun = client.post(
        f"/api/ptmapper/files/{pt_id}/rerun", {"discard_edits": True}, format="json"
    )
    assert rerun.status_code == 200
    row = rerun.json()["rows"][0]
    assert row["data"].get("FIT", "") == ""  # back to the engine value (blank)
    assert rerun.json()["manually_edited"] is False


# ---------------------------------------------------------------- no-clobber invariant


def test_approved_rule_fills_blanks_without_touching_manual_cells(steward_client, vocab):
    pt_id, row_id = _upload(steward_client, vocab, b"BARCODE,COLOR,QTY,MRP\nB1,MISTYX,2,100\n")
    steward_client.patch(  # hand-fix FIT (COLOR is still an unmapped blank)
        f"/api/ptmapper/files/{pt_id}/rows",
        {"rows": [{"id": row_id, "data": {"FIT": "SLIM"}}]},
        format="json",
    )
    prop = LookupProposal.objects.create(
        dimension="color",
        source_key="MISTYX",
        target_value="BLUE",
        brand="PETER ENGLAND",
        origin="mined",
    )
    approve = steward_client.post(
        f"/api/ptmapper/proposals/{prop.id}/decide", {"action": "approve"}, format="json"
    )
    assert approve.status_code == 200, approve.json()
    row = steward_client.get(f"/api/ptmapper/files/{pt_id}").json()["rows"][0]
    assert row["data"]["COLOR"] == "BLUE"  # the learned rule filled the blank
    assert row["provenance"]["COLOR"] == "alias"
    assert row["data"]["FIT"] == "SLIM"  # the manual cell was untouched
    assert row["provenance"]["FIT"] == "manual"


def test_repropagate_skips_sent_and_posted_files(steward_client, vocab):
    sent = PtFile.objects.create(
        original_filename="sent.xlsx",
        row_count=1,
        draft_stage=PtFile.DraftStage.SENT,
        sent_at=timezone.now(),
    )
    row = PtRow.objects.create(
        pt_file=sent,
        line_no=1,
        data={"COLOR": "", "BRAND": "PETER ENGLAND"},
        blanks=["COLOR"],
        provenance={},
        raw={"COLOR": "MISTYX"},
    )
    prop = LookupProposal.objects.create(
        dimension="color",
        source_key="MISTYX",
        target_value="BLUE",
        brand="PETER ENGLAND",
        origin="mined",
    )
    steward_client.post(
        f"/api/ptmapper/proposals/{prop.id}/decide", {"action": "approve"}, format="json"
    )
    row.refresh_from_db()
    sent.refresh_from_db()
    assert row.data["COLOR"] == ""  # frozen — a sent file is never re-mapped
    assert sent.status != PtFile.Status.FAILED  # it was skipped, not processed


# ---------------------------------------------------------------- dropped-cell report


def test_reapply_reports_a_cell_whose_row_vanished(vocab):
    pt = PtFile.objects.create(original_filename="x.xlsx", row_count=1)
    PtRow.objects.create(pt_file=pt, line_no=1, data={"FIT": ""}, blanks=["FIT"], raw={})
    # the snapshot references line 2, which the re-map didn't produce → it is dropped
    blank_cells, applied, dropped = _reapply_manual(pt, {2: {"FIT": "SLIM"}}, blank_cells=1)
    assert (applied, dropped) == (0, 1)


# ---------------------------------------------------------------- manual clear re-opens a blank


def test_reapply_reopens_a_manually_cleared_controlled_cell(vocab):
    """An operator who deliberately clears a controlled cell must not have it read as
    filled: re-applying a manual '' re-opens the blank and re-counts it, even when the
    engine's fresh map had filled that cell (so it wasn't in the rebuilt blanks)."""
    pt = PtFile.objects.create(original_filename="c.xlsx", row_count=1)
    # the fresh engine map filled COLOR (not blank, absent from `blanks`)
    PtRow.objects.create(pt_file=pt, line_no=1, data={"COLOR": "BLUE"}, blanks=[], raw={})
    blank_cells, applied, dropped = _reapply_manual(pt, {1: {"COLOR": ""}}, blank_cells=0)
    row = pt.rows.get()
    assert row.data["COLOR"] == ""  # the manual clear is re-applied
    assert "COLOR" in row.blanks  # blank tracking reflects it
    assert blank_cells == 1  # the running count re-opened the blank
    assert (applied, dropped) == (1, 0)
