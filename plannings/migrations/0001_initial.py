from django.db import migrations, models
import plannings.models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Planning",
            fields=[
                ("id", models.CharField(default=plannings.models.new_uuid, max_length=36, primary_key=True, serialize=False)),
                ("scheduler_uuid", models.CharField(db_index=True, max_length=36, unique=True)),
                ("status", models.CharField(db_index=True, max_length=40)),
                ("input_payload", models.JSONField()),
                ("output_payload", models.JSONField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("progress_percentage", models.IntegerField(default=0)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("duration_seconds", models.FloatField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.CharField(blank=True, max_length=255, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]
