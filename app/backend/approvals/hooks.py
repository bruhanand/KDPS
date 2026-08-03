"""What a document is allowed to do when its own approval clears.

Almost every wired family posts *after* approval, by its maker, and registers
nothing here. Damage flags (#138) cannot: the maker is a store person whom the
ruling bars from moving stock, so if the confirmation did not post, nobody left
in the flow could.

The owning module registers a callback for its own model in ``AppConfig.ready``;
``approvals`` calls it and never learns what it is approving (ADR-0002 — a
module's database is private, and the import-linter contract keeps it that way).
The callback runs inside the decision's transaction, so the movement and the
decision commit together, or roll back together.
"""

from __future__ import annotations

from typing import Any, Protocol


class OnApproved(Protocol):
    """What a registered callback is handed: the document, and who decided."""

    def __call__(self, subject: Any, *, actor: Any) -> None: ...


_ON_APPROVED: dict[type, OnApproved] = {}


def register_on_approved(model: type, callback: OnApproved) -> None:
    """Say that ``model``'s approval is what posts it.

    Registered once at app-ready, so every route to a decision — API, shell,
    management command — goes through the same callback.
    """
    _ON_APPROVED[model] = callback


def run_on_approved(subject: Any, *, actor: Any) -> None:
    """Hand an approved document its own decision, if it asked for it.

    Unregistered types — the ordinary approve-then-post families — pass through
    untouched. A callback that refuses (the flagged piece was sold while it
    waited) raises ``ApprovalError``, which the decide endpoint answers 400 to.
    """
    callback = _ON_APPROVED.get(type(subject))
    if callback is not None:
        callback(subject, actor=actor)
