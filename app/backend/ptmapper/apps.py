from django.apps import AppConfig


class PtmapperConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ptmapper"

    def ready(self) -> None:
        # What cancelling a PT file undoes (#220). Its reversal predates the
        # kernel's and is more than a value mirror - it mints its own PT number
        # for the reversing stock rows, reverses the vendor bill, and un-bumps the
        # booking - so it is declared rather than taking the value-only floor.
        # Declaring it is what makes a bare `pt.cancel()` typed at a shell do the
        # whole job; the API's "Reverse posting" button now runs that same path
        # instead of a parallel one.
        from core.reversal import declare_reversal
        from ptmapper.models import PtFile
        from stockledger.posting import reverse_pt_postings

        declare_reversal(PtFile._meta.label_lower, reverse_pt_postings)
