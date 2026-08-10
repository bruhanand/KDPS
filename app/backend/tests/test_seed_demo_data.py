"""seed_demo_data: a fresh DB completes green, a second run is a clean no-op,
and the two root defects that used to break it stay fixed (#158 umbrella,
folding in #205, #251, #252, #256).

1. The seed used to post PT/V-flip value as the receiving store's warehouse
   login, which the posting floor rightly refuses (a named head-office person
   must post value to the books). Fixed by posting through Accounts/Owner.
2. The RTV and V-flip demo lines used to name barcodes no receipt in the
   seed's own inbound step ever brought in, so the cost resolver could not
   price them and the whole atomic run rolled back. Fixed by pointing every
   line at a SKU-store pair the seed's own `_seed_inbound` actually stocked.
"""

from __future__ import annotations

from django.core.management import call_command

from core.gl import GLEntry, trial_balance
from outbound.models import ReturnToVendorLine, VFlipLine
from stockledger.models import StockOnHand
from vendors.models import Booking

# The exact barcodes the seed used to reference before this fix landed - no
# receipt in the seed's own inbound step ever priced any of them at the store
# the RTV/V-flip line named. Any of these three reappearing in a posted line
# is the historical bug walking back in.
NEVER_RECEIVED_BARCODES = {"PE-CHK-BLU-42", "BB-TROU-GRY-34", "LP-SLIM-WHT-38"}

# The six locations `seed_foundation` creates (5 selling stores + the Ranchi
# warehouse) - the acceptance criterion is "all six stores stocked".
ALL_STORE_CODES = {"DEO", "BKR", "HZB", "DUM", "BANKA", "RAN-WH"}


def test_seed_demo_data_runs_green_on_a_fresh_db_and_a_second_run_is_a_clean_noop(db):
    call_command("seed_demo_data")

    bookings = Booking.objects.count()
    assert bookings > 0

    stocked_stores = set(
        StockOnHand.objects.filter(net_qty__gt=0).values_list("store__code", flat=True)
    )
    assert stocked_stores == ALL_STORE_CODES

    assert trial_balance() == 0  # every posting's legs sum to zero, so does the whole GL

    # A second consecutive run must not crash or duplicate the wave - it
    # recognises its own sentinel and skips.
    call_command("seed_demo_data")
    assert Booking.objects.count() == bookings


def test_seed_demo_data_never_posts_pt_or_vflip_value_as_a_store_scoped_actor(db):
    """Regression for #158/#205: the seed's PT and V-flip value legs must be
    posted by a named head-office person, never the receiving store's own
    warehouse or store login - the posting floor refuses that on sight.
    """
    call_command("seed_demo_data")

    value_entries = GLEntry.objects.filter(doc_type__in=["PT", "VFL"]).select_related(
        "posted_by", "posted_by__role"
    )
    assert value_entries.exists()
    for entry in value_entries:
        actor = entry.posted_by
        assert actor is not None, f"{entry.doc_type} {entry.doc_number} posted with no named actor"
        assert actor.scope_type != "store", (
            f"{entry.doc_type} {entry.doc_number} was posted by {actor.username}, "
            "a store-scoped actor the floor should have refused"
        )


def test_seed_demo_data_rtv_and_vflip_lines_never_reference_an_unreceived_sku(db):
    """Regression for #251/#252/#256: every RTV/V-flip demo line must name a
    SKU-store pair the seed's own inbound step actually stocked, never a
    barcode invented for the line that no receipt ever priced.
    """
    call_command("seed_demo_data")

    rtv_skus = set(ReturnToVendorLine.objects.values_list("sku_code", flat=True))
    vflip_skus = set(VFlipLine.objects.values_list("sku_code", flat=True))
    assert rtv_skus, "expected at least one seeded RTV line"
    assert vflip_skus, "expected at least one seeded V-flip line"

    used = rtv_skus | vflip_skus
    assert not used & NEVER_RECEIVED_BARCODES

    # Every line carries the unit cost `resolve_line_identity` derived at
    # posting time - a line that could not be priced would have raised and
    # rolled the whole seed back, so a positive cost here is the line's own
    # proof it was priceable at its store.
    for rtv_line in ReturnToVendorLine.objects.all():
        assert rtv_line.unit_cost_paise > 0, f"RTV line {rtv_line.sku_code} posted with no cost"
    for vflip_line in VFlipLine.objects.all():
        assert vflip_line.unit_cost_paise > 0, (
            f"V-flip line {vflip_line.sku_code} posted with no cost"
        )


def test_seed_demo_data_failure_names_the_step_and_leaves_no_trace(db, monkeypatch):
    """A failure must end with one clear sentence naming the failed step, and
    stdout must not claim progress a rolled-back transaction just undid
    (#158's cross-cutting requirement - #251/#252/#256 all hit a traceback a
    dozen printed lines in, with nothing saying that progress was gone).
    """
    from django.core.management.base import CommandError

    from outbound.management.commands import seed_demo_data as seed_module

    def _boom(self):
        raise ValueError("synthetic failure for the seed's own step-labelling")

    monkeypatch.setattr(seed_module.Command, "_seed_rtvs", _boom)

    try:
        call_command("seed_demo_data")
    except CommandError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected seed_demo_data to raise CommandError")

    assert "RTVs" in message
    assert "synthetic failure" in message
    assert Booking.objects.count() == 0  # the atomic transaction rolled back cleanly
