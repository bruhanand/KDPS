from django.db import migrations

#: The one chain the system starts with (#172, D10 §3).
#:
#: A store asking another location for stock is first sanity-checked by its
#: *own* manager — the ask came from their counter and it is theirs to stand
#: behind — and then decided by the Operations Head, who is the one person with
#: sight of both ends of a move (#137).
#:
#: Step 2 carries ``later_step_may_short_circuit``, which is the direct-approve
#: ruling in one flag: the Operations Head does not wait for the manager's tap,
#: and the step below closes behind them, recorded as closed *by the Operations
#: Head*. The conversation with the holding store's manager is that step's human
#: work, not a system step — the design says so explicitly, and adding a third
#: step for it would put a gate in front of a phone call.
#:
#: Roles match the seeded ``stock_request`` policy's own list at step 2, so the
#: Owner keeps the sign-off they already had.
STEPS = [
    {
        "order": 1,
        "roles": ["store_manager"],
        "label": "Store manager",
        "later_step_may_short_circuit": False,
    },
    {
        "order": 2,
        "roles": ["ho_ops", "owner"],
        "label": "Operations Head",
        "later_step_may_short_circuit": True,
    },
]


def seed_route(apps, schema_editor):
    ApprovalRoute = apps.get_model("approvals", "ApprovalRoute")
    ApprovalRoute.objects.get_or_create(kind="stock_request", defaults={"steps": STEPS})


def unseed_route(apps, schema_editor):
    ApprovalRoute = apps.get_model("approvals", "ApprovalRoute")
    ApprovalRoute.objects.filter(kind="stock_request", steps=STEPS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0007_approval_routes"),
    ]

    operations = [migrations.RunPython(seed_route, unseed_route)]
