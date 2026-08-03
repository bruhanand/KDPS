"""The bell's data: a read cursor, an alerts history, two approvals filters (#226).

The bell stops being a link to `/approvals` and becomes a two-tab popup, so it
needs three things the server did not offer before:

- **A read cursor.** Approvals clear by *deciding* - a fact the server already
  holds. Alerts clear by *reading*, which nothing recorded, so an alerts badge
  had nowhere to count from. One stamp per person, on the server's clock, so it
  survives a logout and follows the person to the next device.
- **Resolved alerts.** The open feed filters to `open` by design; History is the
  other half of the same lifecycle, scoped identically - nobody sees a store in
  history they cannot see live.
- **Decided approvals in a window.** The audit list already exists; it grows two
  filters so the popup can ask for "decisions, recently" without pulling every
  approval ever made through the wire.

Seams: the API seam only. Nothing here posts, and no document or ledger moves.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from alerts.models import Alert, AlertKind, AlertSeen, AlertStatus
from approvals.models import Approval, ApprovalStatus
from masters.models import Brand, Gstin, LegalEntity, Store

pytestmark = pytest.mark.django_db(transaction=True)

SEEN = "/api/alerts/seen"
HISTORY = "/api/alerts/history"
APPROVALS = "/api/approvals"


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture()
def bell(db):
    """Two stores, a brand, and the four people who read the bell: HO (sees the
    network), each store's manager (sees their own), and a role that reaches
    nothing at all - the fail-closed case the gate has to answer 403 to."""
    entity = LegalEntity.objects.create(code="be-ent", name="Bell Entity", pan="AAACB1234C")
    gstin = Gstin.objects.create(
        gstin="10AAACB1234C1ZS", state_code="10", state_name="Bihar", legal_entity=entity
    )
    store = Store.objects.create(code="BE-A", name="Bell Store A", gstin=gstin)
    other_store = Store.objects.create(code="BE-B", name="Bell Store B", gstin=gstin)
    brand = Brand.objects.create(
        code="be-br",
        name="BellBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    ho_role = make_role("ho_ops", "HO Ops (bell test)")
    manager_role = make_role("store_manager", "Store manager (bell test)")
    # Built by hand rather than through `make_role`: every ratified role reaches
    # Home, and the point of this one is that it reaches nothing.
    shut_out_role = Role.objects.create(
        code="be_shut_out", name="Reaches nothing (bell test)", section_access={}
    )

    def _user(username, role, scope=ScopeType.ALL, stores=()):
        u = User.objects.create_user(
            username=username, password=TEST_PASSWORD, role=role, entity=entity, scope_type=scope
        )
        for s in stores:
            u.stores.add(s)
        return u

    return {
        "entity": entity,
        "gstin": gstin,
        "store": store,
        "other_store": other_store,
        "brand": brand,
        "ho": _user("be_ho", ho_role),
        "maker": _user("be_maker", ho_role),
        "manager": _user("be_manager", manager_role, ScopeType.STORE, [store]),
        "other_manager": _user("be_other_manager", manager_role, ScopeType.STORE, [other_store]),
        "shut_out": _user("be_shut_out_user", shut_out_role),
    }


def _alert(store, *, title, status=AlertStatus.OPEN, resolved_days_ago=None, created_days_ago=0):
    """One alert on `store`. `resolved_days_ago` puts it in history."""
    alert = Alert.objects.create(
        kind=AlertKind.IN_TRANSIT_AGING,
        kind_label="Transfer stuck in transit",
        title=title,
        dedupe_key=title,
        store=store,
        status=status,
        resolved_at=(
            None
            if resolved_days_ago is None
            else timezone.now() - timedelta(days=resolved_days_ago)
        ),
    )
    if created_days_ago:
        # `created_at` is auto_now_add, so it can only be moved after the insert.
        Alert.objects.filter(pk=alert.pk).update(
            created_at=timezone.now() - timedelta(days=created_days_ago)
        )
        alert.refresh_from_db()
    return alert


def _approval(bell, *, status, days_ago=0, title="BE/STO/26-27/1"):
    """One approval on the bell store, decided `days_ago` where the status says
    a person decided it."""
    decided = status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
    approval = Approval.objects.create(
        kind="writeoff",
        kind_label="Write-off",
        title=title,
        content_type=ContentType.objects.get_for_model(Store),
        object_id=bell["store"].pk,
        store=bell["store"],
        value_paise=100_00,
        made_by=bell["maker"],
        requested_by=bell["maker"],
        status=status,
        decided_by=bell["ho"] if decided else None,
        decided_at=timezone.now() - timedelta(days=days_ago) if decided else None,
        reason="because" if status == ApprovalStatus.REJECTED else "",
    )
    return approval


# ---------------------------------------------------------------------------
# The read cursor
# ---------------------------------------------------------------------------


def test_a_person_who_has_never_opened_the_tab_has_no_stamp(bell):
    """No row means "never seen", which the client reads as all-unread - the
    right cold start for everyone who exists today."""
    resp = _client(bell["manager"]).get(SEEN)
    assert resp.status_code == 200, resp.data
    assert resp.data == {"seen_at": None}


def test_stamping_records_the_server_clock_and_reads_back(bell):
    before = timezone.now()
    resp = _client(bell["manager"]).post(SEEN)
    assert resp.status_code == 200, resp.data
    stamped = resp.data["seen_at"]
    assert stamped is not None

    row = AlertSeen.objects.get(user=bell["manager"])
    assert before <= row.seen_at <= timezone.now()

    read = _client(bell["manager"]).get(SEEN)
    assert read.data["seen_at"] == stamped


def test_stamping_twice_moves_one_row_forward(bell):
    """Idempotent upsert: the tab is opened many times a day and must not grow a
    row each time, nor fail on the second."""
    first = _client(bell["manager"]).post(SEEN).data["seen_at"]
    second = _client(bell["manager"]).post(SEEN).data["seen_at"]
    assert AlertSeen.objects.filter(user=bell["manager"]).count() == 1
    assert second >= first


def test_one_persons_stamp_is_not_anothers(bell):
    _client(bell["manager"]).post(SEEN)
    assert _client(bell["other_manager"]).get(SEEN).data["seen_at"] is None


def test_the_stamp_is_gated_on_home_view(bell):
    shut_out = _client(bell["shut_out"])
    assert shut_out.get(SEEN).status_code == 403
    assert shut_out.post(SEEN).status_code == 403


def test_the_stamp_needs_a_token(bell):
    assert APIClient().get(SEEN).status_code == 401
    assert APIClient().post(SEEN).status_code == 401


# ---------------------------------------------------------------------------
# Alerts history
# ---------------------------------------------------------------------------


def test_history_lists_resolved_alerts_newest_first_and_never_open_ones(bell):
    _alert(bell["store"], title="still true", status=AlertStatus.OPEN)
    _alert(
        bell["store"], title="cleared 3 days ago", status=AlertStatus.RESOLVED, resolved_days_ago=3
    )
    _alert(bell["store"], title="cleared today", status=AlertStatus.RESOLVED, resolved_days_ago=0)

    resp = _client(bell["ho"]).get(HISTORY)
    assert resp.status_code == 200, resp.data
    assert [row["title"] for row in resp.data] == ["cleared today", "cleared 3 days ago"]


def test_history_defaults_to_the_last_seven_days(bell):
    _alert(bell["store"], title="inside", status=AlertStatus.RESOLVED, resolved_days_ago=6)
    _alert(bell["store"], title="outside", status=AlertStatus.RESOLVED, resolved_days_ago=30)

    resp = _client(bell["ho"]).get(HISTORY)
    assert [row["title"] for row in resp.data] == ["inside"]


def test_history_honours_an_explicit_since(bell):
    _alert(bell["store"], title="inside", status=AlertStatus.RESOLVED, resolved_days_ago=30)
    _alert(bell["store"], title="outside", status=AlertStatus.RESOLVED, resolved_days_ago=400)

    resp = _client(bell["ho"]).get(HISTORY, {"since": _days_back(365)})
    assert [row["title"] for row in resp.data] == ["inside"]


def test_history_is_scoped_like_the_live_feed(bell):
    """The acceptance criterion in one test: a store person never meets another
    store's resolved alert, exactly as they never meet its open one."""
    _alert(bell["store"], title="mine", status=AlertStatus.RESOLVED, resolved_days_ago=1)
    _alert(bell["other_store"], title="theirs", status=AlertStatus.RESOLVED, resolved_days_ago=1)

    assert [r["title"] for r in _client(bell["manager"]).get(HISTORY).data] == ["mine"]
    assert [r["title"] for r in _client(bell["other_manager"]).get(HISTORY).data] == ["theirs"]


@pytest.mark.parametrize("bad", ["yesterday", "2026-02-30", "31-07-2026", "2026-7"])
def test_history_refuses_a_since_that_is_not_a_date(bell, bad):
    """Both of `parse_date`'s refusals - nonsense, and well-shaped impossible -
    are one 400 with one code, never a 500."""
    resp = _client(bell["ho"]).get(HISTORY, {"since": bad})
    assert resp.status_code == 400, resp.data
    assert resp.data["code"] == "INVALID_SINCE"


def test_history_is_gated_on_home_view(bell):
    assert _client(bell["shut_out"]).get(HISTORY).status_code == 403
    assert APIClient().get(HISTORY).status_code == 401


def test_resolved_at_joins_the_alert_shape_without_disturbing_the_open_feed(bell):
    """One new nullable field, and that is the whole change to the existing
    consumers of `GET /api/alerts`."""
    _alert(bell["store"], title="still true", status=AlertStatus.OPEN)
    open_row = _client(bell["ho"]).get("/api/alerts").data[0]
    assert open_row["resolved_at"] is None

    _alert(bell["store"], title="cleared", status=AlertStatus.RESOLVED, resolved_days_ago=1)
    assert _client(bell["ho"]).get(HISTORY).data[0]["resolved_at"] is not None


# ---------------------------------------------------------------------------
# Approvals history: the two new filters
# ---------------------------------------------------------------------------


def test_decided_keeps_only_what_a_person_decided(bell):
    """`not_required` is a real row - "auto-cleared, logged" - and it belongs on
    the full screen, not in a history of decisions nobody made."""
    _approval(bell, status=ApprovalStatus.APPROVED, title="approved")
    _approval(bell, status=ApprovalStatus.REJECTED, title="rejected")
    _approval(bell, status=ApprovalStatus.NOT_REQUIRED, title="auto")
    _approval(bell, status=ApprovalStatus.PENDING, title="waiting")

    resp = _client(bell["ho"]).get(APPROVALS, {"decided": "1"})
    assert resp.status_code == 200, resp.data
    assert sorted(row["title"] for row in resp.data) == ["approved", "rejected"]


def test_since_filters_on_the_decision_and_drops_the_undecided(bell):
    _approval(bell, status=ApprovalStatus.APPROVED, days_ago=2, title="recent")
    _approval(bell, status=ApprovalStatus.APPROVED, days_ago=40, title="old")
    _approval(bell, status=ApprovalStatus.PENDING, title="waiting")

    resp = _client(bell["ho"]).get(APPROVALS, {"since": _days_back(7)})
    assert [row["title"] for row in resp.data] == ["recent"]


def test_the_two_filters_compose_with_the_existing_ones(bell):
    _approval(bell, status=ApprovalStatus.APPROVED, days_ago=1, title="approved")
    _approval(bell, status=ApprovalStatus.REJECTED, days_ago=1, title="rejected")

    resp = _client(bell["ho"]).get(
        APPROVALS, {"decided": "1", "since": _days_back(7), "status": "rejected"}
    )
    assert [row["title"] for row in resp.data] == ["rejected"]


def test_the_audit_list_is_unchanged_without_the_new_params(bell):
    """Existing callers ask nothing new and get everything, as before."""
    _approval(bell, status=ApprovalStatus.APPROVED, title="approved")
    _approval(bell, status=ApprovalStatus.NOT_REQUIRED, title="auto")
    _approval(bell, status=ApprovalStatus.PENDING, title="waiting")

    resp = _client(bell["ho"]).get(APPROVALS)
    assert sorted(row["title"] for row in resp.data) == ["approved", "auto", "waiting"]


@pytest.mark.parametrize("bad", ["yesterday", "2026-02-30"])
def test_approvals_refuses_a_since_that_is_not_a_date(bell, bad):
    """The same code and the same shape as the alerts history - one behaviour
    the popup can handle in one place."""
    resp = _client(bell["ho"]).get(APPROVALS, {"since": bad})
    assert resp.status_code == 400, resp.data
    assert resp.data["code"] == "INVALID_SINCE"


def test_approvals_history_stays_store_scoped(bell):
    _approval(bell, status=ApprovalStatus.APPROVED, days_ago=1, title="bell store")
    assert [r["title"] for r in _client(bell["manager"]).get(APPROVALS, {"decided": "1"}).data] == [
        "bell store"
    ]
    assert _client(bell["other_manager"]).get(APPROVALS, {"decided": "1"}).data == []


def _days_back(days: int) -> str:
    """A `since` value `days` before today, on the store's calendar (IST) - the
    same calendar the server filters on."""
    return (timezone.localdate() - timedelta(days=days)).isoformat()
