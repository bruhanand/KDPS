"""Grant the new ``staff`` section on already-seeded roles (issue #87).

#85 shipped twelve sections; the 13-section sidebar adds ``staff`` (Attendance
now, Members pending). ``Role.section_access`` rows written before this point
have no ``staff`` key, and an absent key fail-closes to ``none`` — so without
this backfill the section would be invisible to everyone until a re-seed.

Only the missing key is added. Every other cell is left exactly as it is, so a
role a live admin has already retuned keeps that tuning (Rule 12: access is
their data, not ours).
"""

from django.db import migrations


def add_staff_section(apps, schema_editor):
    from accounts.rbac_matrix import section_access_for

    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        access = role.section_access or {}
        if "staff" in access:
            continue
        access["staff"] = section_access_for(role.code)["staff"]
        role.section_access = access
        role.save(update_fields=["section_access"])


def drop_staff_section(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        access = role.section_access or {}
        if access.pop("staff", None) is not None:
            role.section_access = access
            role.save(update_fields=["section_access"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_backfill_section_access"),
    ]

    operations = [
        migrations.RunPython(add_staff_section, drop_staff_section),
    ]
