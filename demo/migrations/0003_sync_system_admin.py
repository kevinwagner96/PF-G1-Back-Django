from django.db import migrations


def sync_system_admin(apps, schema_editor):
    from demo.seed import seed_demo_data

    seed_demo_data()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_system_admin_permission"),
        ("demo", "0002_sync_demo_groups"),
    ]

    operations = [migrations.RunPython(sync_system_admin, migrations.RunPython.noop)]
