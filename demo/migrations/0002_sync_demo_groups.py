from django.db import migrations


def sync_groups(apps, schema_editor):
    from demo.seed import seed_demo_data

    seed_demo_data()


class Migration(migrations.Migration):
    dependencies = [
        ("demo", "0001_seed_demo"),
        ("plannings", "0002_planning_permissions"),
    ]

    operations = [migrations.RunPython(sync_groups, migrations.RunPython.noop)]
