from django.db import migrations, models


def backfill_kind(apps, schema_editor):
    """Existing GRNs predate the branded/non-branded split. A direct (booking-less)
    receipt was warehouse intake — the non-branded path; a receipt against a booking
    was a branded order to a store. Key off ``is_direct``, not ``booking__isnull``:
    booking is a ``SET_NULL`` FK, so a branded GRN whose booking was later deleted has
    a null booking yet ``is_direct=False`` — keying on booking would wrongly flip it to
    non-branded. ``is_direct`` is the immutable receipt marker set at creation. (The
    AddField default already set every row to ``branded``, so we only flip the direct
    receipts.)"""
    Grn = apps.get_model("inbound", "Grn")
    Grn.objects.filter(is_direct=True).update(kind="non_branded")


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
