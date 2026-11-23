from django.db import migrations


def configure(apps, schema_editor):
    from demo.seed import configure_demo_chiefs

    configure_demo_chiefs(apps, schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [
        ("demo", "0004_admin_can_approve_planning"),
        ("plannings", "0006_preserve_historical_agendas"),
    ]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
