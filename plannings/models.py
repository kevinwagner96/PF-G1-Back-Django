import uuid

from django.conf import settings
from django.db import models


def new_uuid() -> str:
    return str(uuid.uuid4())


class Planning(models.Model):
    STATUS_PLANNING = "planning"
    STATUS_PENDING_APPROVAL = "pending_approval"
    STATUS_FAILED = "failed"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    ACTIVE_STATUSES = [STATUS_PLANNING, STATUS_PENDING_APPROVAL]

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
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.CharField(max_length=255, null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("can_create_planning", "Can create planning"),
            ("can_approve_planning", "Can approve planning"),
        ]


class PlanningAuditEvent(models.Model):
    class Action(models.TextChoices):
        PLANNING_REQUESTED = "planning_requested", "Planning requested"
        PLANNING_REQUEST_FAILED = "planning_request_failed", "Planning request failed"
        PLANNING_CREATED = "planning_created", "Planning created"
        SCHEDULER_CALLBACK_COMPLETED = (
            "scheduler_callback_completed",
            "Scheduler callback completed",
        )
        SCHEDULER_CALLBACK_FAILED = "scheduler_callback_failed", "Scheduler callback failed"
        PLANNING_PENDING_APPROVAL = "planning_pending_approval", "Planning pending approval"
        PLANNING_APPROVED = "planning_approved", "Planning approved"
        PLANNING_REJECTED = "planning_rejected", "Planning rejected"
        PLANNING_DELETED = "planning_deleted", "Planning deleted"
        SURGERY_SCHEDULED_FROM_PLANNING = (
            "surgery_scheduled_from_planning",
            "Surgery scheduled from planning",
        )

    class Source(models.TextChoices):
        USER = "user", "User"
        SCHEDULER = "scheduler", "Scheduler"
        SYSTEM = "system", "System"

    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    action = models.CharField(max_length=80, choices=Action.choices, db_index=True)
    planning = models.ForeignKey(
        Planning,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    surgery = models.ForeignKey(
        "surgeries.Surgery",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="planning_audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="planning_audit_events",
    )
    actor_email = models.CharField(max_length=255, null=True, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, db_index=True)
    summary = models.CharField(max_length=500)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
