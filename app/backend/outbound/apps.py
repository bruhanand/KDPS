from django.apps import AppConfig


class OutboundConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "outbound"

    def ready(self) -> None:
        """Say which outbound document is posted *by* its own approval (#138).

        Only damage flags are: a store person may report damage but not move
        the stock, so the warehouse's confirmation has to be what posts it.
        Registered here, at app-ready, so every route to a decision — API,
        shell, management command — goes through the same call.
        """
        from approvals.hooks import register_on_approved
        from outbound.models import MarkDamaged
        from outbound.posting import confirm_mark_damaged

        register_on_approved(MarkDamaged, confirm_mark_damaged)
