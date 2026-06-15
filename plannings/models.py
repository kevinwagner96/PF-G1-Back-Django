import uuid

from django.db import models


def new_uuid() -> str:
    return str(uuid.uuid4())


class Planning(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    scheduler_uuid = models.CharField(max_length=36, unique=True, db_index=True)
    status = models.CharField(max_length=40, db_index=True)
    input_payload = models.JSONField()
    output_payload = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    progress_percentage = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
