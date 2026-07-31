"""The dial and the flag kind the nightly check needs (#188).

`SellPolicy.return_review_count` is how many pieces one seller may take back in a
day before the check says so, and `employee_returns` is the row it leaves. The
kind is its own rather than a note on a bill because the finding is a pattern
*across* bills: there is no one bill to hang it on and no one bill that answers
it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sell", "0012_deferred_costing_returned"),
    ]

    operations = [
        migrations.AddField(
            model_name="sellpolicy",
            name="return_review_count",
            field=models.IntegerField(
                default=5,
                help_text="How many pieces one seller may take back in a day before "
                "the daily check puts their name on the store's exception list.",
            ),
        ),
        migrations.AlterField(
            model_name="continuityflag",
            name="kind",
            field=models.CharField(
                choices=[
                    ("number_hole", "Bills missing before this one"),
                    ("cn_unverified", "Credit note taken without verification"),
                    ("return_orig_missing", "Returned against a bill we do not hold"),
                    ("offer_mismatch", "Offer applied differs from the rulebook"),
                    ("gst_mismatch", "Tax charged differs from the dated slab"),
                    ("aged_uncosted", "Sold before inward, still unpriced"),
                    ("gstin_invalid", "The buyer's GSTIN is not well formed"),
                    ("return_late", "Taken back after the return window closed"),
                    ("return_uncosted", "Given back before the books could price it"),
                    ("employee_returns", "One seller took back an unusual number"),
                ],
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="sellpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(("return_review_count__gt", 0)),
                name="ck_sellpolicy_return_review_is_positive",
            ),
        ),
    ]
