"""The `core` app is the kernel: money type, append-only ledgers, the posting
engine, docstatus FSM, naming series, scoping. Empty at K0 — it gains its first
real primitive (MoneyField + the append-only LedgerEntry base) at K1."""

from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
