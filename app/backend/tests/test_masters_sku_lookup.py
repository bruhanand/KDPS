"""SKU-registry reuse lookup (D2 Q16/Q41) — the authoring editor's "seen before →
reuse barcode X" source. Exact-match, never dumps the registry."""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from rest_framework.test import APIClient

from accounts.models import User
from masters.models import Sku


@pytest.fixture
def client(db):
    user = User.objects.create_user(username="lookup", password=TEST_PASSWORD)
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def registry(db):
    Sku.objects.create(
        barcode="8901234",
        design="KURTA-01",
        size="M",
        brand="LOCALWEAR",
        color="BLUE",
        hsn="6204",
        mrp_paise=99900,
    )
    Sku.objects.create(barcode="8905678", design="KURTA-01", size="L", brand="LOCALWEAR")
    Sku.objects.create(barcode="8909999", design="JEANS-77", size="32", brand="KILLER")


def test_lookup_by_design_size_brand(client, registry):
    r = client.get("/api/masters/skus/lookup?design=kurta-01&size=M&brand=LOCALWEAR")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    match = body["matches"][0]
    assert match["barcode"] == "8901234"
    assert match["mrp"] == 999.0  # paise → rupees for the editor cell


def test_lookup_by_design_alone_returns_all_sizes(client, registry):
    r = client.get("/api/masters/skus/lookup?design=KURTA-01")
    assert r.json()["count"] == 2


def test_lookup_requires_design_or_barcode(client, registry):
    assert client.get("/api/masters/skus/lookup").status_code == 400
    assert client.get("/api/masters/skus/lookup?brand=LOCALWEAR").status_code == 400
    assert client.get("/api/masters/skus/lookup?barcode=8909999").json()["count"] == 1
