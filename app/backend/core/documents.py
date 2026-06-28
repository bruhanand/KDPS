"""Document skeleton: docstatus FSM + gap-free naming series (K2, ADR-0004).

The generic skeleton every business document (booking, GRN, PT, sale) inherits —
NOT any business document itself. It owns three things and nothing more:

1. **The docstatus FSM** — `draft → submitted → cancelled`, one `post()` per doc.
   Cancel is a *reversing transition*, never a delete; a posted doc is immutable.
2. **The naming series** — the Tally join key `{FY}/{store}/{seq}` (e.g.
   `26-27/DEO/74`), allocated gap-free and collision-free under parallel insert.
3. **Three keys** per row — surrogate `bigint` PK · business `doc_number` ·
   `idempotency_uuid` (offline-write dedupe).

Ledger posting-leg logic (`post_entries`) is K7 and lives elsewhere — `post()`
here only mints the number and flips the status; the dimensions/snapshots ride
in with K3 and the business slices.

Defence-in-depth mirrors the K1 ledger: the **DB trigger is primary** (it binds
even the superuser CI connects as), the **ORM raises the early, clean error**.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import models, transaction

#: One shared trigger function for every document table.
TRIGGER_FUNCTION = "kdps_document_fsm"


class DocumentError(Exception):
    """Base for every document-skeleton violation."""


class DocumentTransitionError(DocumentError):
    """An illegal docstatus move (skip, cycle, re-post, cancel-a-draft)."""


class DocumentEditError(DocumentError):
    """An attempt to edit or delete a posted/cancelled document."""


class DocStatus(models.IntegerChoices):
    """The lifecycle every document walks, in order. Integer-valued so the DB
    trigger can reason about monotonicity with no table-specific knowledge."""

    DRAFT = 0, "draft"
    SUBMITTED = 1, "submitted"
    CANCELLED = 2, "cancelled"


class VoucherSeries(models.Model):
    """The gap-free counter behind every `doc_number` (store · type · next_seq ·
    prefix/suffix).

    A series is master config (Rule 12 — variation is data): a trained admin adds
    a row, no release. `next_seq` is a plain row counter — *not* a Postgres
    SEQUENCE — because a SEQUENCE leaks gaps on rollback, and the Tally join key
    must be gap-free. Allocation locks the row (`SELECT … FOR UPDATE`) inside the
    posting transaction, so a rolled-back post un-allocates its number.
    """

    fy = models.CharField(max_length=7)  # financial year, e.g. "26-27"
    store_code = models.CharField(max_length=16)  # e.g. "DEO"
    doc_type = models.CharField(max_length=16)  # e.g. "SAL", "GRN", "PT"
    prefix = models.CharField(max_length=32, blank=True, default="")
    suffix = models.CharField(max_length=32, blank=True, default="")
    next_seq = models.BigIntegerField(default=1)

    class Meta:
        db_table = "core_voucher_series"
        constraints = [
            models.UniqueConstraint(
                fields=["fy", "store_code", "doc_type"],
                name="uq_voucher_series_scope",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fy}/{self.store_code}/{self.doc_type} → {self.next_seq}"

    def render(self, seq: int) -> str:
        """Format `seq` as the canonical `{FY}/{store}/{seq}` key, framed by any
        admin-configured prefix/suffix. Empty affixes give `26-27/DEO/74`."""
        return f"{self.prefix}{self.fy}/{self.store_code}/{seq}{self.suffix}"

    @classmethod
    def allocate(cls, *, fy: str, store_code: str, doc_type: str) -> tuple[VoucherSeries, str]:
        """Consume the next number for a series, gap-free and collision-free.

        MUST run inside an outer `transaction.atomic()` (the caller's posting
        transaction): the row lock is held until that transaction commits, so
        concurrent allocators serialise and a rollback returns the number.
        """
        series = cls.objects.select_for_update().get(
            fy=fy, store_code=store_code, doc_type=doc_type
        )
        seq = series.next_seq
        series.next_seq = seq + 1
        series.save(update_fields=["next_seq"])
        return series, series.render(seq)


class DocumentManager(models.Manager["Document"]):
    """Adds the offline-write dedupe entry point to every concrete document."""

    def idempotent_create(self, *, idempotency_uuid: uuid.UUID, **fields: Any) -> Any:
        """Create-or-return by `idempotency_uuid`. A retried offline write with
        the same key returns the original document — never a duplicate. The
        unique column makes the create race-safe (a losing insert re-fetches)."""
        obj, _ = self.get_or_create(idempotency_uuid=idempotency_uuid, defaults=fields)
        return obj


class Document(models.Model):
    """Abstract base carrying the three keys + the docstatus FSM.

    Concrete documents override `series_lookup()` to say which `VoucherSeries`
    mints their number; everything else — the lifecycle, immutability, the
    idempotency key — is inherited unchanged.
    """

    #: Surrogate key (key 1 of 3). `BigAutoField` via DEFAULT_AUTO_FIELD.
    #: Business doc-number (key 2 of 3) — the Tally join key. NULL while a draft;
    #: minted gap-free at post() so an abandoned draft never burns a number.
    doc_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    #: Offline-write dedupe (key 3 of 3). Client-supplied for retries.
    idempotency_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    docstatus = models.IntegerField(choices=DocStatus.choices, default=DocStatus.DRAFT)
    series = models.ForeignKey(VoucherSeries, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: DocumentManager = DocumentManager()

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.doc_number or f"{type(self).__name__}(draft #{self.pk})"

    # -- standard model overrides (immutability guards) ------------------------
    def save(self, *args: Any, **kwargs: Any) -> None:
        in_transition = getattr(self, "_in_transition", False)
        if not self._state.adding and not in_transition:
            loaded = getattr(self, "_loaded_docstatus", None)
            if loaded == DocStatus.SUBMITTED:
                raise DocumentEditError(
                    "a posted document is immutable; cancel and re-issue, never edit"
                )
            if loaded == DocStatus.CANCELLED:
                raise DocumentEditError("a cancelled document is frozen")
            # loaded == DRAFT (or a fresh-in-memory unsaved edit): drafts are
            # editable, but a status change must go through post()/cancel().
            if self.docstatus != DocStatus.DRAFT:
                raise DocumentTransitionError(
                    "use post()/cancel() to change docstatus, not a bare save()"
                )
        super().save(*args, **kwargs)
        self._loaded_docstatus = self.docstatus

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        loaded = getattr(self, "_loaded_docstatus", None)
        if loaded in (DocStatus.SUBMITTED, DocStatus.CANCELLED):
            raise DocumentEditError("a posted/cancelled document is cancelled, never deleted")
        return super().delete(*args, **kwargs)

    @classmethod
    def from_db(cls, db: Any, field_names: Any, values: Any) -> Any:
        instance = super().from_db(db, field_names, values)
        instance._loaded_docstatus = instance.docstatus
        return instance

    # -- series wiring ---------------------------------------------------------
    def series_lookup(self) -> tuple[str, str, str]:
        """Return `(fy, store_code, doc_type)` identifying this doc's series.

        The kernel skeleton is business-agnostic, so the concrete document must
        say where its number comes from. Overridden by every real document.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement series_lookup() to be postable"
        )

    # -- the FSM ---------------------------------------------------------------
    def post(self) -> None:
        """`draft → submitted`: mint the gap-free number, freeze the doc.

        Run inside `transaction.atomic()` so number allocation and the status
        flip commit together (and roll back together — gap-free).
        """
        if self._state.adding:
            raise DocumentTransitionError("save the draft before posting it")
        if self.docstatus != DocStatus.DRAFT:
            raise DocumentTransitionError(
                f"only a draft can be posted; this is {self.get_docstatus_display()}"
            )
        with transaction.atomic():
            fy, store_code, doc_type = self.series_lookup()
            series, number = VoucherSeries.allocate(fy=fy, store_code=store_code, doc_type=doc_type)
            self.series = series
            self.doc_number = number
            self.docstatus = DocStatus.SUBMITTED
            self._save_transition(["series", "doc_number", "docstatus", "updated_at"])

    def cancel(self) -> None:
        """`submitted → cancelled`: a reversing transition, never a delete.

        The row stays; the ledger reversal it triggers is K7's job.
        """
        if self.docstatus != DocStatus.SUBMITTED:
            raise DocumentTransitionError(
                f"only a submitted document can be cancelled; this is "
                f"{self.get_docstatus_display()}"
            )
        self.docstatus = DocStatus.CANCELLED
        self._save_transition(["docstatus", "updated_at"])

    def _save_transition(self, fields: list[str]) -> None:
        self._in_transition = True
        try:
            self.save(update_fields=fields)
        finally:
            self._in_transition = False


def document_fsm_sql(table_name: str) -> str:
    """SQL installing the docstatus FSM trigger on `table_name`.

    Generic over every document table — it references only the `docstatus`
    column, so the same function guards each one. It binds even the superuser CI
    connects as (a trigger, unlike a REVOKE, stops a superuser):

    * no UPDATE may walk backwards or re-post (submitted may only reach cancelled;
      a draft may only stay draft or post);
    * a cancelled row is frozen;
    * a posted/cancelled row may not be DELETEd — it is cancelled, never deleted.
    """
    trigger_name = f"{table_name}_document_fsm"
    return f"""
    CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.docstatus <> 0 THEN
                RAISE EXCEPTION
                    'docstatus FSM: a posted/cancelled row in % is cancelled, never deleted',
                    TG_TABLE_NAME;
            END IF;
            RETURN OLD;
        END IF;
        IF OLD.docstatus = 2 THEN
            RAISE EXCEPTION 'docstatus FSM: a cancelled row in % is frozen', TG_TABLE_NAME;
        ELSIF OLD.docstatus = 1 AND NEW.docstatus <> 2 THEN
            RAISE EXCEPTION
                'docstatus FSM: a submitted row in % may only move to cancelled', TG_TABLE_NAME;
        ELSIF OLD.docstatus = 0 AND NEW.docstatus NOT IN (0, 1) THEN
            RAISE EXCEPTION
                'docstatus FSM: a draft row in % may only stay draft or be posted', TG_TABLE_NAME;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}();
    """


def document_fsm_reverse_sql(table_name: str) -> str:
    """Reverse of `document_fsm_sql` for one table (leaves the shared function)."""
    return f"DROP TRIGGER IF EXISTS {table_name}_document_fsm ON {table_name};"


class DocumentProbe(Document):
    """Kernel-internal concrete document that exercises the skeleton against real
    Postgres — NOT a business document.

    The real booking/GRN/PT/sale arrive with their slices. This exists only so
    the FSM trigger and the gap-free series genuinely run in the DB and the K2
    golden tests have a concrete table to post against. It carries the minimum to
    resolve a series plus a free-text `memo` to prove edit-after-post is refused.
    """

    fy = models.CharField(max_length=7)
    store_code = models.CharField(max_length=16)
    doc_type = models.CharField(max_length=16)
    memo = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "core_document_probe"

    def series_lookup(self) -> tuple[str, str, str]:
        return self.fy, self.store_code, self.doc_type
