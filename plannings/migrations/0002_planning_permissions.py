from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plannings", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="planning",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("can_create_planning", "Can create planning"),
                    ("can_approve_planning", "Can approve planning"),
                ],
            },
        ),
    ]
