from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_user_groups_alter_user_is_active_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [
                    ("can_access_system_admin", "Can access system admin"),
                ],
            },
        ),
    ]
