"""Deterministic miner + shadow validation (Slice 4 of the self-improving mapper).

The miner turns the SENT-file correction log into staged proposals — never live
rules. It enforces ≥ min-support corrections across ≥ 2 distinct files for a
brand-scoped rule, ≥ 2 agreeing brands for a global rule, refuses ambiguous groups,
ignores files that never reached Patna, is idempotent, and auto-rejects a proposal
that would flip a human-confirmed cell.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.utils import timezone

from ptmapper.engine import norm
from ptmapper.models import ControlledValue, CorrectionEvent, PtFile, PtRow

COL = {"fit": "FIT", "color": "COLOR", "size": "SIZE"}


@pytest.fixture
def vocab(db):
    for dim, values in {
        "brand": ["PETER ENGLAND", "ZILU", "MUFTI"],
        "color": ["BLUE", "RED"],
        "fit": ["SLIM", "REGULAR"],
        "size": ["M", "L"],
    }.items():
        for v in values:
            ControlledValue.objects.create(dimension=dim, value=v)


def _file(name, stage=PtFile.DraftStage.SENT):
    return PtFile.objects.create(
        original_filename=name,
        row_count=1,
        draft_stage=stage,
        sent_at=timezone.now() if stage == PtFile.DraftStage.SENT else None,
    )


def _ev(file, dim, raw, new, brand, kind="cell"):
    return CorrectionEvent.objects.create(
        pt_file=file,
        file_name=file.original_filename,
        line_no=1,
        dimension=dim,
        column=COL[dim],
        raw_value=raw,
        new_value=new,
        brand=brand,
        edit_kind=kind,
    )


def _props(**kw):
    from ptmapper.models import LookupProposal

    return LookupProposal.objects.filter(**kw)


# ---------------------------------------------------------------- thresholds


def test_brand_scoped_needs_three_across_two_files(vocab):
    fa, fb = _file("pe-a.xlsx"), _file("pe-b.xlsx")
    _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    _ev(fb, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_mine")
    p = _props(dimension="fit", source_key="OCTANE").get()
    assert (p.origin, p.status, p.brand, p.target_value) == (
        "mined",
        "proposed",
        "PETER ENGLAND",
        "REGULAR",
    )
    assert p.evidence["occurrences"] == 3


def test_single_file_repetition_never_proposes(vocab):
    fa = _file("pe-a.xlsx")
    for _ in range(5):  # 5 events but all on ONE file → below the ≥2-files bar
        _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_mine")
    assert not _props(dimension="fit", source_key="OCTANE").exists()


def test_conflicting_targets_never_propose(vocab):
    fa, fb, fc, fd = (_file(f"pe-{i}.xlsx") for i in range(4))
    _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    _ev(fb, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    _ev(fc, "fit", "OCTANE", "SLIM", "PETER ENGLAND")
    _ev(fd, "fit", "OCTANE", "SLIM", "PETER ENGLAND")
    call_command("ptmap_mine")
    assert not _props(dimension="fit", source_key="OCTANE").exists()  # ambiguous → skip


def test_non_sent_files_never_feed_proposals(vocab):
    fa = _file("pe-a.xlsx", stage=PtFile.DraftStage.MAPPING)
    fb = _file("pe-b.xlsx", stage=PtFile.DraftStage.MAPPING)
    _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    _ev(fb, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_mine")
    assert not _props(dimension="fit", source_key="OCTANE").exists()  # D1: not yet at Patna


# ---------------------------------------------------------------- global consensus


def test_global_needs_two_agreeing_brands(vocab):
    fa, fb = _file("pe.xlsx"), _file("zilu.xlsx")
    _ev(fa, "color", "MISTY", "BLUE", "PETER ENGLAND")
    _ev(fb, "color", "MISTY", "BLUE", "ZILU")  # two brands agree → global rule
    call_command("ptmap_mine")
    p = _props(dimension="color", source_key="MISTY").get()
    assert (p.brand, p.target_value, p.status) == ("", "BLUE", "proposed")


def test_single_brand_scopes_not_global(vocab):
    fa, fb = _file("pe-a.xlsx"), _file("pe-b.xlsx")
    for f in (fa, fb, fa):
        _ev(f, "color", "MISTY", "BLUE", "PETER ENGLAND")
    call_command("ptmap_mine")
    p = _props(dimension="color", source_key="MISTY").get()
    assert p.brand == "PETER ENGLAND"  # one brand → brand-scoped, never global


# ---------------------------------------------------------------- shadow + idempotency


def test_shadow_auto_rejects_a_manual_cell_flip(vocab):
    # a SENT Peter England file confirms FIT=SLIM (manual) for raw 'OCTANE' — the row
    # carries its resolved BRAND, so a PE-scoped proposal conflicts with it (D4).
    confirmed = _file("confirmed.xlsx")
    PtRow.objects.create(
        pt_file=confirmed,
        line_no=1,
        data={"BRAND": "PETER ENGLAND", "FIT": "SLIM"},
        provenance={"FIT": "manual"},
        raw={"FIT": "OCTANE"},
    )
    # yet other PETER ENGLAND files' corrections say OCTANE→REGULAR
    fa, fb = _file("pe-a.xlsx"), _file("pe-b.xlsx")
    for f in (fa, fb, fa):
        _ev(f, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_mine")
    p = _props(dimension="fit", source_key="OCTANE").get()
    assert p.status == "auto_rejected"  # a promotion must never flip a confirmed cell
    assert any(c["kind"] == "manual_cell_conflict" for c in p.validation["conflicts"])


def test_rerun_mints_no_duplicates(vocab):
    fa, fb = _file("pe-a.xlsx"), _file("pe-b.xlsx")
    for f in (fa, fb, fa):
        _ev(f, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_mine")
    call_command("ptmap_mine")  # idempotent — the partial-unique index holds
    assert _props(dimension="fit", source_key="OCTANE", status="proposed").count() == 1


def test_covered_pairs_are_skipped(vocab):
    from ptmapper.models import Lookup

    Lookup.objects.create(
        dimension="fit", source_key="OCTANE", target_value="REGULAR", brand="PETER ENGLAND"
    )
    fa, fb = _file("pe-a.xlsx"), _file("pe-b.xlsx")
    for f in (fa, fb, fa):
        _ev(f, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_mine")
    assert not _props(dimension="fit", source_key="OCTANE").exists()  # already a live rule


def test_learning_report_runs(vocab):
    fa = _file("pe-a.xlsx")
    _ev(fa, "fit", "OCTANE", "REGULAR", "PETER ENGLAND")
    call_command("ptmap_learning_report")  # smoke: read-only, must not raise
    assert norm("x") == "X"
