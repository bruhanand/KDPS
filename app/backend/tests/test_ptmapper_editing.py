"""Master-Sheet dropdown editing + fill-rate features (July 2026 slice).

Covers:
  * fit_code_candidates — the coded Peter England FIT TYPE parser (pure);
  * rolling_season_values — the seed's rolling season window (pure);
  * PATCH /ptmapper/files/<pk>/rows — rejects non-Master values with per-cell
    errors, writes valid ones as provenance 'manual', recomputes NAG/MARGIN;
  * bulk fills — blank / all / match_raw scopes;
  * GET /ptmapper/controlled — the one-request dropdown payload;
  * engine fallbacks — brand-level default gender, operator context
    (brand + invoice date) for brand-less/date-less files.
"""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from ptmapper.engine import Resolver, fit_code_candidates, map_record, run_mapping
from ptmapper.management.commands.seed_ptmapper import rolling_season_values
from ptmapper.models import ControlledValue, ItemTaxonomy, Lookup, PtFile, PtRow

# ---------------------------------------------------------------- pure functions


def test_fit_code_candidates_orders_full_value_then_token_then_trailing_word():
    assert fit_code_candidates("PJ RG OCTANEMIDSTR") == [
        "PJ RG OCTANEMIDSTR",
        "RG",
        "OCTANEMIDSTR",
    ]
    assert fit_code_candidates("PC SL Snug") == ["PC SL SNUG", "SL", "SNUG"]
    assert fit_code_candidates("PC RG Regular") == ["PC RG REGULAR", "RG", "REGULAR"]
    # a plain fit string stays a single candidate — the normal lookup path
    assert fit_code_candidates("SLIM FIT") == ["SLIM FIT"]
    assert fit_code_candidates("") == []


def test_rolling_season_window_covers_start_to_horizon():
    seasons = rolling_season_values(date(2026, 7, 2))
    assert "SPRING SUMMER(Jan-25)" in seasons
    assert "AUTUMN WINTER(Dec-26)" in seasons
    assert "AUTUMN WINTER(Jul-27)" in seasons  # ~12 months out
    assert "SPRING SUMMER(Jan-28)" in seasons  # 18 months out
    assert "AUTUMN WINTER(Dec-24)" not in seasons  # before the window


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def vocab(db):
    for dim, values in {
        "season": ["SPRING SUMMER(Jun-26)", "AUTUMN WINTER(Oct-25)"],
        "brand": ["PETER ENGLAND", "JOCKEY"],
        "color": ["BLUE", "RED"],
        "gender": ["MALE", "FEMALE", "UNISEX"],
        "sub_category": ["CASUAL WEAR", "FORMAL WEAR"],
        "type": ["TOP WEAR", "BOTTOM WEAR"],
        "item": ["SHIRT", "JEANS"],
        "fit": ["SLIM", "REGULAR"],
        "size": ["M", "L", "XL"],
        "gst": ["5", "12", "18", "TAX FREE"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)
    ItemTaxonomy.objects.create(item="SHIRT", sub_category="CASUAL WEAR", type="TOP WEAR")
    Lookup.objects.create(dimension="brand_gender", source_key="PETER ENGLAND", target_value="MALE")
    Lookup.objects.create(dimension="fit", source_key="RG", target_value="REGULAR")
    Lookup.objects.create(dimension="fit", source_key="SL", target_value="SLIM")


@pytest.fixture
def client(db):
    user = User.objects.create_user(username="editor", password="x")
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def pt_file(db):
    pt = PtFile.objects.create(original_filename="edit-me.xlsx", row_count=2)
    r1 = PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={
            "BRAND": "",
            "GENDER": "",
            "QTY": 2,
            "MRP": 100,
            "P RATE": 60,
            "NAG": 2,
            "MARGIN": 40.0,
            "SEASON": "",
        },
        blanks=["BRAND", "GENDER", "SEASON"],
        provenance={},
        raw={"BRAND": "PJ", "SEASON": ""},
    )
    r2 = PtRow.objects.create(
        pt_file=pt,
        line_no=2,
        data={
            "BRAND": "JOCKEY",
            "GENDER": "MALE",
            "QTY": 1,
            "MRP": 200,
            "P RATE": 100,
            "NAG": 1,
            "MARGIN": 50.0,
            "SEASON": "",
        },
        blanks=["SEASON"],
        provenance={"BRAND": "direct"},
        raw={"BRAND": "JOCKEY", "SEASON": ""},
    )
    return pt, r1, r2


# ---------------------------------------------------------------- PATCH validation


def test_patch_rejects_non_master_value_with_per_cell_errors(client, vocab, pt_file):
    pt, r1, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r1.id, "data": {"GENDER": "MENS", "BRAND": "PETER ENGLAND"}}]},
        format="json",
    )
    assert resp.status_code == 400
    errs = resp.json()["errors"]
    assert len(errs) == 1
    assert errs[0]["column"] == "GENDER" and errs[0]["row_id"] == r1.id
    r1.refresh_from_db()
    assert r1.data["GENDER"] == ""  # nothing was written — all-or-nothing
    assert r1.data["BRAND"] == ""


def test_patch_accepts_master_values_and_marks_manual(client, vocab, pt_file):
    pt, r1, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r1.id, "data": {"GENDER": "MALE", "INPUT TAX": "5"}}]},
        format="json",
    )
    assert resp.status_code == 200
    r1.refresh_from_db()
    assert r1.data["GENDER"] == "MALE"
    assert r1.provenance["GENDER"] == "manual"
    assert "GENDER" not in r1.blanks


def test_patch_allows_blanking_a_controlled_cell(client, vocab, pt_file):
    pt, _, r2 = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r2.id, "data": {"GENDER": ""}}]},
        format="json",
    )
    assert resp.status_code == 200
    r2.refresh_from_db()
    assert r2.data["GENDER"] == ""
    assert "GENDER" in r2.blanks


def test_patch_recomputes_nag_and_margin(client, vocab, pt_file):
    pt, r1, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"rows": [{"id": r1.id, "data": {"QTY": "5", "P RATE": "50"}}]},
        format="json",
    )
    assert resp.status_code == 200
    r1.refresh_from_db()
    assert r1.data["NAG"] == 5
    assert r1.data["MARGIN"] == 50.0  # (100 - 50) / 100
    assert r1.provenance["NAG"] == "derived"
    assert r1.provenance["MARGIN"] == "derived"


# ---------------------------------------------------------------- bulk fills


def test_bulk_fill_blank_scope_only_touches_blank_cells(client, vocab, pt_file):
    pt, r1, r2 = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"fills": [{"column": "BRAND", "value": "PETER ENGLAND", "scope": "blank"}]},
        format="json",
    )
    assert resp.status_code == 200
    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.data["BRAND"] == "PETER ENGLAND"  # was blank → filled
    assert r2.data["BRAND"] == "JOCKEY"  # had a value → untouched


def test_bulk_fill_all_scope_overwrites_every_row(client, vocab, pt_file):
    pt, r1, r2 = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"fills": [{"column": "SEASON", "value": "SPRING SUMMER(Jun-26)", "scope": "all"}]},
        format="json",
    )
    assert resp.status_code == 200
    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.data["SEASON"] == r2.data["SEASON"] == "SPRING SUMMER(Jun-26)"
    assert r1.provenance["SEASON"] == "manual"


def test_bulk_fill_match_raw_scope_targets_rows_by_source_value(client, vocab, pt_file):
    pt, r1, r2 = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"fills": [{"column": "BRAND", "value": "PETER ENGLAND", "scope": {"match_raw": "PJ"}}]},
        format="json",
    )
    assert resp.status_code == 200
    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.data["BRAND"] == "PETER ENGLAND"  # raw BRAND was 'PJ'
    assert r2.data["BRAND"] == "JOCKEY"  # raw BRAND was 'JOCKEY' → untouched


def test_bulk_fill_rejects_non_master_value(client, vocab, pt_file):
    pt, _, _ = pt_file
    resp = client.patch(
        f"/api/ptmapper/files/{pt.id}/rows",
        {"fills": [{"column": "BRAND", "value": "NOT A BRAND", "scope": "all"}]},
        format="json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------- /controlled


def test_controlled_no_param_returns_all_dimensions_and_taxonomy(client, vocab):
    resp = client.get("/api/ptmapper/controlled")
    assert resp.status_code == 200
    body = resp.json()
    assert "PETER ENGLAND" in body["dimensions"]["brand"]
    assert body["dimensions"]["gst"] == ["12", "18", "5", "TAX FREE"]
    assert body["item_taxonomy"]["SHIRT"] == {"sub_category": "CASUAL WEAR", "type": "TOP WEAR"}


def test_controlled_single_dimension_form_unchanged(client, vocab):
    resp = client.get("/api/ptmapper/controlled?dimension=gender")
    assert resp.status_code == 200
    assert resp.json() == {"dimension": "gender", "values": ["FEMALE", "MALE", "UNISEX"]}


# ---------------------------------------------------------------- engine fallbacks


def test_brand_gender_is_the_last_gender_fallback(vocab):
    resolver = Resolver()
    profile = {"code": "generic", "overrides": {}, "flags": {}}
    rec = {"BARCODE": "B1", "QTY": 1, "MRP": 100, "BRAND": "PETER ENGLAND"}
    row, _, prov, _ = map_record(rec, profile, resolver, "")
    assert row["GENDER"] == "MALE"
    assert prov["GENDER"] == "inferred"
    # ...but a gender word in the description still wins over the brand default
    rec2 = {**rec, "ITEM DESCRIPTION": "WOMENS SHIRT"}
    row2, _, prov2, _ = map_record(rec2, profile, resolver, "")
    assert row2["GENDER"] == "FEMALE"


def test_coded_fit_type_resolves_via_token(vocab):
    resolver = Resolver()
    profile = {
        "code": "pe",
        "overrides": {"FIT_SRC": "FIT TYPE"},
        "flags": {"fit_code_tokens": True},
    }
    rec = {"BARCODE": "B1", "QTY": 1, "MRP": 100, "FIT TYPE": "PJ RG OCTANEMIDSTR"}
    row, _, prov, _ = map_record(rec, profile, resolver, "")
    assert row["FIT"] == "REGULAR"
    assert prov["FIT"] == "alias"
    # an unknown code maps nothing and lands one review miss under the full raw
    rec2 = {**rec, "FIT TYPE": "PJ ZZ MYSTERY"}
    row2, _, _, _ = map_record(rec2, profile, resolver, "")
    assert row2["FIT"] == ""
    assert ("fit|PJ ZZ MYSTERY") in resolver.misses


def test_upload_context_fills_brand_and_season_for_bare_files(vocab):
    csv = b"BARCODE,QTY,MRP\nB1,2,100\nB2,1,200\n"
    res = run_mapping(
        csv,
        "no name here.csv",
        "text/csv",
        {"brand": "JOCKEY", "invoice_date": "2026-06-15"},
    )
    assert len(res["rows"]) == 2
    for r in res["rows"]:
        assert r["data"]["BRAND"] == "JOCKEY"
        assert r["provenance"]["BRAND"] == "derived"
        assert r["data"]["SEASON"] == "SPRING SUMMER(Jun-26)"
        assert r["provenance"]["SEASON"] == "derived"
    # context suppressed the filename-stem brand guess → no brand miss queued
    assert not [m for m in res["reviews"] if m["dimension"] == "brand"]


def test_without_context_bare_file_maps_no_brand(vocab):
    csv = b"BARCODE,QTY,MRP\nB1,2,100\n"
    res = run_mapping(csv, "no name here.csv", "text/csv")
    assert res["rows"][0]["data"]["BRAND"] == ""
    assert res["rows"][0]["data"]["SEASON"] == ""


# ---------------------------------------------------------------- upload API context


def test_upload_rejects_unknown_context_brand(client, vocab):
    from django.core.files.uploadedfile import SimpleUploadedFile

    up = SimpleUploadedFile("x.csv", b"BARCODE,QTY,MRP\nB1,1,100\n", content_type="text/csv")
    resp = client.post(
        "/api/ptmapper/files", {"file": up, "brand": "NOT A BRAND"}, format="multipart"
    )
    assert resp.status_code == 400
    assert "Master-Sheet brand" in resp.json()["detail"]


def test_upload_context_is_stored_canonically_and_applied(client, vocab):
    from django.core.files.uploadedfile import SimpleUploadedFile

    up = SimpleUploadedFile("x.csv", b"BARCODE,QTY,MRP\nB1,1,100\n", content_type="text/csv")
    resp = client.post(
        "/api/ptmapper/files",
        {"file": up, "brand": "jockey", "invoice_date": "2026-06-15"},
        format="multipart",
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["meta"]["context"] == {"brand": "JOCKEY", "invoice_date": "2026-06-15"}
    assert body["rows"][0]["data"]["BRAND"] == "JOCKEY"
    assert body["rows"][0]["data"]["SEASON"] == "SPRING SUMMER(Jun-26)"
