"""Uploaded documents kept as Postgres blobs + metadata."""

from __future__ import annotations

from django.db import models

from core.base import TimeStampedModel


class StoredFile(TimeStampedModel):
    class Kind(models.TextChoices):
        BOOKING_RECEIPT = "booking_receipt", "Booking receipt"
        INVOICE = "invoice", "Invoice"
        PT_FILE = "pt_file", "PT file"
        OTHER = "other", "Other"

    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size = models.IntegerField(default=0)
    content = models.BinaryField()
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    def __str__(self) -> str:
        return f"{self.filename} ({self.kind})"

    @classmethod
    def from_upload(cls, upload, kind: str, user=None) -> "StoredFile":
        data = upload.read()
        return cls.objects.create(
            filename=getattr(upload, "name", "upload"),
            content_type=getattr(upload, "content_type", "application/octet-stream")
            or "application/octet-stream",
            size=len(data),
            content=data,
            kind=kind,
            uploaded_by=user if getattr(user, "is_authenticated", False) else None,
        )
