from django.db import migrations


def seed(apps, schema_editor):
    from demo.seed import seed_demo_data

    seed_demo_data()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("surgeries", "0001_initial"),
        ("plannings", "0001_initial"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
