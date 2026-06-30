"""Upload size cap (review medium: from_upload had no size limit).

A blob over MAX_UPLOAD_BYTES is refused before it is read into memory / the DB.
The size check short-circuits, so the oversized case never allocates the bytes.
"""

from __future__ import annotations

import pytest

from files.models import MAX_UPLOAD_BYTES, StoredFile, UploadTooLarge


class _FakeUpload:
    def __init__(self, size: int):
        self.size = size
        self.name = "file.xlsx"
        self.content_type = "application/octet-stream"

    def read(self) -> bytes:
        return b"x" * self.size


def test_oversized_upload_is_rejected(db):
    with pytest.raises(UploadTooLarge):
        StoredFile.from_upload(_FakeUpload(MAX_UPLOAD_BYTES + 1), StoredFile.Kind.OTHER, None)


def test_small_upload_is_stored(db):
    stored = StoredFile.from_upload(_FakeUpload(10), StoredFile.Kind.OTHER, None)
    assert stored.size == 10
