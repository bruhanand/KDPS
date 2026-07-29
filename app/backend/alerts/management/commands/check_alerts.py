"""Run both alert checks and sync the alerts table (#77).

Scheduled daily via render.yaml (``kdps-alerts-check``). Idempotent — safe to
run by hand, or more than once on the same day.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from alerts.checks import run_alert_checks


class Command(BaseCommand):
    help = "Run the in-transit-aging and return-window alert checks."

    def handle(self, *args: Any, **options: Any) -> None:
        counts = run_alert_checks()
        self.stdout.write(
            self.style.SUCCESS(
                f"Alerts synced — in-transit aging: {counts['in_transit_aging']}, "
                f"return window: {counts['return_window']}"
            )
        )
