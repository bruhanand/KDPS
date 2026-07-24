"""Give the store *manager* the Staff section their sketch asks for (issue #96).

#87 seeded both store roles from one "Store Person" persona, so a manager and a
cashier came out identical: ``staff: operate`` — own attendance only. The
hand-drawn Store Ops screen puts "Member Details" (add/remove members, contact
and bank details, monthly target vs achievement) in the store's own list, and
that is manager work. ``ROLE_OVERRIDES`` now lifts ``store_manager`` to
``staff: manage``; this backfill moves the rows already in the database.

Only a row still sitting at the seeded default is touched. If a live admin has
already retuned this cell, their value wins — access is their data (Rule 12).
The cashier is not touched at all.
"""

from django.db import migrations

SEEDED_DEFAULT = "operate"
ROLE_CODE = "store_manager"


def _retune(apps, capability: str, label: str, *, only_if: str) -> None:
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.filter(code=ROLE_CODE):
        access = role.section_access or {}
        current = access.get("staff")
        if not current or current.get("capability") != only_if:
            continue  # never seeded, or an admin has already retuned it
        access["staff"] = {"capability": capability, "label": label}
        role.section_access = access
        role.save(update_fields=["section_access"])


def grant_members(apps, schema_editor):
    from accounts.rbac_matrix import section_access_for

    cell = section_access_for(ROLE_CODE)["staff"]
    _retune(apps, cell["capability"], cell["label"], only_if=SEEDED_DEFAULT)


def revoke_members(apps, schema_editor):
    from accounts.rbac_matrix import MATRIX

    capability, label = MATRIX["store_person"]["staff"]
    _retune(apps, capability, label, only_if="manage")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_add_staff_section_access"),
    ]

    operations = [
        migrations.RunPython(grant_members, revoke_members),
    ]
