from django.db import migrations, models


def backfill_kind(apps, schema_editor):
    """Existing GRNs predate the branded/non-branded split. Booking-linked receipts
    were branded orders against a store; booking-less direct receipts were warehouse
    intake — the non-branded path. Backfill accordingly (the AddField default already
    set every row to ``branded``, so we only flip the direct receipts)."""
    Grn = apps.get_model("inbound", "Grn")
    Grn.objects.filter(booking__isnull=True).update(kind="non_branded")


class Migration(migrations.Migration):

    dependencies = [
        ("inbound", "0004_remove_grn_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="grn",
            name="kind",
            field=models.CharField(
                choices=[("branded", "Branded"), ("non_branded", "Non-branded")],
                default="branded",
                max_length=12,
            ),
        ),
        migrations.RunPython(backfill_kind, migrations.RunPython.noop),
    ]
