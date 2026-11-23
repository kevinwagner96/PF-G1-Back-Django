import uuid

from django.conf import settings
from django.db import models, router, transaction


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
    week_start = models.DateField(null=True, blank=True, db_index=True)
    operational = models.BooleanField(default=False)
    status = models.CharField(max_length=40, db_index=True)
    current_version = models.ForeignKey(
        "PlanningVersion", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    applied_version = models.ForeignKey(
        "PlanningVersion", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
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
            ("can_edit_specialty_planning", "Can edit planning for own specialties"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["week_start"], condition=models.Q(operational=True),
                name="unique_operational_planning_week",
            ),
            models.CheckConstraint(
                condition=models.Q(operational=False) | models.Q(week_start__isnull=False),
                name="operational_planning_requires_week",
            ),
        ]


class PlanningVersion(models.Model):
    class Origin(models.TextChoices):
        SCHEDULER = "scheduler", "Generación inicial"
        ORDINARY = "ordinary", "Edición manual"
        URGENT = "urgent", "Ajuste urgente"
        HISTORICAL = "historical", "Agenda histórica"

    planning = models.ForeignKey(Planning, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    origin = models.CharField(max_length=20, choices=Origin.choices)
    assignments = models.JSONField(default=dict)
    changes = models.JSONField(default=list)
    reason = models.TextField(blank=True)
    actor_name = models.CharField(max_length=255, blank=True)
    urgent_surgery = models.ForeignKey(
        "surgeries.Surgery", null=True, blank=True, on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["planning", "number"], name="unique_planning_version"),
        ]


class SpecialtyChief(models.Model):
    specialty = models.OneToOneField("surgeries.Specialty", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    designation = models.UUIDField(default=uuid.uuid4, editable=False)

    def clean(self):
        from django.core.exceptions import ValidationError

        from surgeries.models import MedicalStaff

        if self.user_id and self.specialty_id:
            if not self.user.is_active or self.user.bloqueado or not MedicalStaff.objects.filter(
                pk=self.user.personal_id, estado=True, rol__iexact="cirujano",
                especialidades=self.specialty, especialidades__estado=True,
            ).exists():
                raise ValidationError({"user": "El jefe debe ser un cirujano activo de la especialidad."})

    def save(self, *args, **kwargs):
        from surgeries.models import Specialty

        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            Specialty.objects.using(database).select_for_update(no_key=True).get(pk=self.specialty_id)
            previous = type(self).objects.using(database).filter(pk=self.pk).first() if self.pk else None
            if previous:
                fields = kwargs.get("update_fields")
                changed = (
                    (fields is None or {"user_id", "user"} & set(fields)) and previous.user_id != self.user_id
                ) or (
                    (fields is None or {"specialty_id", "specialty"} & set(fields))
                    and previous.specialty_id != self.specialty_id
                )
                self.designation = uuid.uuid4() if changed else previous.designation
                if changed and fields is not None:
                    kwargs["update_fields"] = {*fields, "designation"}
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.specialty.nombre} — {self.user.nombre}"


class PlanningVote(models.Model):
    version = models.ForeignKey(PlanningVersion, on_delete=models.CASCADE, related_name="votes")
    designation = models.UUIDField()
    specialty_id = models.CharField(max_length=36)
    specialty_name = models.CharField(max_length=120)
    actor_id = models.PositiveBigIntegerField()
    actor_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "designation"], name="unique_designation_vote"),
        ]


class PlanningEditLock(models.Model):
    planning = models.OneToOneField(Planning, on_delete=models.CASCADE, related_name="edit_lock")
    version = models.ForeignKey(PlanningVersion, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_digest = models.CharField(max_length=64)
    token = models.UUIDField(default=uuid.uuid4, editable=False)
    urgent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class AppliedSurgery(models.Model):
    planning = models.ForeignKey(Planning, on_delete=models.CASCADE, related_name="applied_surgeries")
    surgery = models.OneToOneField("surgeries.Surgery", on_delete=models.CASCADE)


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
        LOCK_ACQUIRED = "lock_acquired", "Edición iniciada"
        LOCK_RELEASED = "lock_released", "Edición cerrada"
        LOCK_RECOVERED = "lock_recovered", "Bloqueo recuperado"
        VERSION_SAVED = "version_saved", "Versión guardada"
        VOTE_RECORDED = "vote_recorded", "Voto registrado"
        URGENCY_APPLIED = "urgency_applied", "Urgencia aplicada"
        SURGERY_CANCELLED = "surgery_cancelled", "Cirugía cancelada"
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
