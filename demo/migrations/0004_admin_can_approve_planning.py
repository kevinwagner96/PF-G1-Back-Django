from django.db import migrations


def grant_admin_approval_permission(apps, schema_editor):
    from demo.seed import sync_demo_groups_and_permissions

    sync_demo_groups_and_permissions()


class Migration(migrations.Migration):
    dependencies = [
        ("demo", "0003_sync_system_admin"),
        ("plannings", "0004_planning_rejected_at_planning_rejected_by_and_more"),
    ]

    operations = [migrations.RunPython(grant_admin_approval_permission, migrations.RunPython.noop)]
