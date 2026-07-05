"""Codex correctness fixes (issue #48): PT-file store scoping + one-live-PT-per-GRN.

The brand-PT upload path (`POST /ptmapper/files` with a ``grn``) and the PT-file
list bypassed the fail-closed store scoping that ``/inbound/grns`` already applies,
and the one-live-PT check had no row lock or DB backstop. This covers:

  * a store-scoped user cannot GRN-link or list another store's PT (fail-closed);
  * an unrestricted (scope=all) user is unaffected;
  * the partial-unique DB constraint rejects a second live PT for one GRN, while a
    NULL grn (legacy grn-less upload) is exempt.
"""

from __future__ import annotations

from datetime import date

import pytest
from _creds import TEST_PASSWORD
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from core.documents import VoucherSeries
from files.models import StoredFile
from inbound.models import Grn, GrnLine
from masters.models import Gstin, LegalEntity, Store
from ptmapper.models import ControlledValue, Lookup, PtFile
from stockledger.posting import financial_year

# ---------------------------------------------------------------- fixtures


@pytest.fixture
def world(db):
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10ABCDE1234F1Z5", state_code="10", state_name="Bihar"
    )
    fy = financial_year(date.today())
    wh1 = Store.objects.create(
        code="RAN-WH", name="Ranchi WH", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    wh2 = Store.objects.create(
        code="PAT-WH", name="Patna WH", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    for wh in (wh1, wh2):
        VoucherSeries.objects.get_or_create(fy=fy, store_code=wh.code, doc_type="GRN")
    return {"wh1": wh1, "wh2": wh2}


@pytest.fixture
def vocab(db):
    for dim, values in {"brand": ["LOCALWEAR"], "color": ["BLUE"], "size": ["M"]}.items():
        for v in values:
            ControlledValue.objects.get_or_create(dimension=dim, value=v)
    for dim, key, target in [
        ("brand", "LOCALWEAR", "LOCALWEAR"),
        ("color", "BLUE", "BLUE"),
        ("size", "M", "M"),
    ]:
        Lookup.objects.get_or_create(dimension=dim, source_key=key, target_value=target, brand="")


def _user(username: str, role_code: str, *, scope: str, stores: list[Store] | None = None) -> User:
    role, _ = Role.objects.get_or_create(code=role_code, defaults={"name": role_code})
    user = User.objects.create_user(username=username, password=TEST_PASSWORD, role=role)
    user.scope_type = scope
    user.save(update_fields=["scope_type"])
    if stores:
        user.stores.set(stores)
    return user


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user)
    return c


LINES = [{"style_code": "KURTA-01", "size": "M", "color": "Blue", "received_qty": 4}]

_BRAND_CSV = b"STYLE,SIZE,COLOR,QTY\nKURTA-01,M,Blue,4\n"


def _grn(store: Store) -> Grn:
    grn = Grn.objects.create(
        store=store,
        received_at=Grn.ReceivedAt.WAREHOUSE,
        kind=Grn.Kind.NON_BRANDED,
        is_direct=True,
        vendor_name_raw="Localwear Traders",
        invoice_number="INV-77",
    )
    for raw in LINES:
        GrnLine.objects.create(grn=grn, **raw)
    grn.post()
    return grn


def _upload_brand_pt(client: APIClient, grn_id: int):
    return client.post(
        "/api/ptmapper/files",
        {
            "file": SimpleUploadedFile("brand.csv", _BRAND_CSV, content_type="text/csv"),
            "grn": grn_id,
        },
        format="multipart",
    )


# --------------------------------------------------------- GRN-link scoping (Codex #2)


def test_scoped_user_cannot_link_pt_to_out_of_scope_grn(world, vocab):
    """A user scoped to wh1 may not link a brand PT to wh2's GRN — fail-closed 404,
    identical to how the GRN would be invisible on /inbound/grns."""
    grn = _grn(world["wh2"])
    client = _client(_user("wh1-op", "warehouse", scope=ScopeType.STORE, stores=[world["wh1"]]))
    r = _upload_brand_pt(client, grn.id)
    assert r.status_code == 404, r.content
    assert not PtFile.objects.filter(grn=grn).exists()
    assert not StoredFile.objects.exists()


def test_scoped_user_can_link_pt_to_in_scope_grn(world, vocab):
    grn = _grn(world["wh1"])
    client = _client(_user("wh1-op", "warehouse", scope=ScopeType.STORE, stores=[world["wh1"]]))
    r = _upload_brand_pt(client, grn.id)
    assert r.status_code == 201, r.content
    assert r.json()["grn"] == grn.id


def test_unrestricted_user_can_link_any_grn(world, vocab):
    grn = _grn(world["wh2"])
    client = _client(_user("boss", "owner", scope=ScopeType.ALL))
    r = _upload_brand_pt(client, grn.id)
    assert r.status_code == 201, r.content


def test_duplicate_grn_link_does_not_store_orphaned_file(world, vocab):
    grn = _grn(world["wh1"])
    existing = PtFile.objects.create(original_filename="first.csv", grn=grn)
    client = _client(_user("wh1-op", "warehouse", scope=ScopeType.STORE, stores=[world["wh1"]]))
    r = _upload_brand_pt(client, grn.id)
    assert r.status_code == 409, r.content
    assert r.json()["pt_file_id"] == existing.id
    assert not StoredFile.objects.exists()


# ---------------------------------------------------------- PT-list scoping (Codex #2)


def test_pt_list_is_scoped_by_grn_store(world, vocab):
    mine = PtFile.objects.create(original_filename="mine.csv", grn=_grn(world["wh1"]))
    PtFile.objects.create(original_filename="theirs.csv", grn=_grn(world["wh2"]))
    client = _client(_user("wh1-op", "warehouse", scope=ScopeType.STORE, stores=[world["wh1"]]))
    ids = [p["id"] for p in client.get("/api/ptmapper/files").json()]
    assert ids == [mine.id]


def test_pt_list_unrestricted_sees_all(world, vocab):
    PtFile.objects.create(original_filename="a.csv", grn=_grn(world["wh1"]))
    PtFile.objects.create(original_filename="b.csv", grn=_grn(world["wh2"]))
    client = _client(_user("boss", "owner", scope=ScopeType.ALL))
    assert len(client.get("/api/ptmapper/files").json()) == 2


# ------------------------------------------------- one-live-PT-per-GRN DB constraint (#3)


def test_second_live_pt_for_one_grn_is_rejected(world):
    grn = _grn(world["wh1"])
    PtFile.objects.create(original_filename="first.csv", grn=grn)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PtFile.objects.create(original_filename="second.csv", grn=grn)


def test_grn_less_uploads_are_exempt_from_the_constraint(db):
    # Legacy grn-less brand uploads (NULL grn) must not collide with each other.
    PtFile.objects.create(original_filename="a.csv")
    PtFile.objects.create(original_filename="b.csv")
    assert PtFile.objects.filter(grn__isnull=True).count() == 2
