"""Put the bills that have been waiting too long to be costed in front of a human.

The costing queue drains itself: a PT lands, the sweep posts, the row goes. This
is what happens when it *doesn't* - a PT nobody sent, a brand nobody added, a
supplier nobody named. Past the dial's number of days the line stops being "the
paperwork is on its way" and becomes somebody's job, and this is what says so.

Runs daily, idempotent by construction - a bill already carrying an open
`aged_uncosted` flag does not get a second one. It is a separate command today
because the daily check it belongs inside (`sell_daily_check`, #188) is not built
yet; when it is, this becomes one of its steps rather than a second schedule.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from sell.services.costing_sweep import age_deferred


class Command(BaseCommand):
    help = "Flag bills whose sold-before-inward lines have waited too long to be costed."

    def handle(self, *args: Any, **options: Any) -> None:
        raised = age_deferred()
        self.stdout.write(self.style.SUCCESS(f"Aged uncosted lines flagged on {raised} bill(s)."))
