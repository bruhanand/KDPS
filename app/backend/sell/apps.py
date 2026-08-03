from django.apps import AppConfig


class SellConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sell"

    def ready(self) -> None:
        # The deferred-costing sweep listens for the two things that can release a
        # bill nobody could cost on the day (#186). Imported for its side effect,
        # which is what `ready()` is for.
        from sell import signals  # noqa: F401
