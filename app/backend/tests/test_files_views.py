"""Unit tests for files.views and files.models — covering upload, download, and
size cap enforcement."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import User
from files.models import MAX_UPLOAD_BYTES, StoredFile, UploadTooLarge


@pytest.fixture
def auth_client(db):
    user = User.objects.create_user(username="fileuser", password="File@Pass123")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# --- StoredFile.from_upload ---------------------------------------------------


@pytest.mark.django_db
class TestStoredFileFromUpload:
    def test_successful_upload(self):
        user = User.objects.create_user(username="uploader", password="Up@Pass123")
        upload = SimpleUploadedFile("test.pdf", b"fake-pdf-content", content_type="application/pdf")
        stored = StoredFile.from_upload(upload, StoredFile.Kind.INVOICE, user)
        assert stored.filename == "test.pdf"
        assert stored.content_type == "application/pdf"
        assert stored.size == len(b"fake-pdf-content")
        assert stored.kind == StoredFile.Kind.INVOICE
        assert stored.uploaded_by == user

    def test_upload_without_user(self):
        upload = SimpleUploadedFile("anon.txt", b"data", content_type="text/plain")
        stored = StoredFile.from_upload(upload, StoredFile.Kind.OTHER, None)
        assert stored.uploaded_by is None

    def test_upload_too_large_by_size_attr(self):
        upload = SimpleUploadedFile("big.bin", b"x", content_type="application/octet-stream")
        upload.size = MAX_UPLOAD_BYTES + 1
        with pytest.raises(UploadTooLarge):
            StoredFile.from_upload(upload, StoredFile.Kind.OTHER)

    def test_upload_too_large_by_content(self):
        data = b"x" * (MAX_UPLOAD_BYTES + 1)

        class FakeUpload:
            name = "huge.bin"
            content_type = "application/octet-stream"
            size = None  # no size attr to trigger the second check

            def read(self):
                return data

        with pytest.raises(UploadTooLarge):
            StoredFile.from_upload(FakeUpload(), StoredFile.Kind.OTHER)


# --- Download view -------------------------------------------------------------


@pytest.mark.django_db
class TestDownloadView:
    def test_download_file(self, auth_client):
        client, user = auth_client
        stored = StoredFile.objects.create(
            filename="doc.pdf",
            content_type="application/pdf",
            size=7,
            content=b"payload",
            kind=StoredFile.Kind.PT_FILE,
            uploaded_by=user,
        )
        resp = client.get(f"/api/files/{stored.pk}/download")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert b"payload" in resp.content
        assert 'filename="doc.pdf"' in resp["Content-Disposition"]

    def test_download_not_found_raises(self, auth_client):
        client, _ = auth_client
        from files.models import StoredFile

        with pytest.raises(StoredFile.DoesNotExist):
            client.get("/api/files/99999/download")

    def test_unauthenticated_blocked(self, auth_client):
        client, user = auth_client
        stored = StoredFile.objects.create(
            filename="secret.pdf",
            content_type="application/pdf",
            size=4,
            content=b"data",
            kind=StoredFile.Kind.OTHER,
        )
        anon = APIClient()
        resp = anon.get(f"/api/files/{stored.pk}/download")
        assert resp.status_code == 401
