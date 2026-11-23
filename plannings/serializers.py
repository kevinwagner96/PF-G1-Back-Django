from rest_framework import serializers

from plannings.agenda import (
    can_edit,
    chiefs,
    effective_agenda,
    eligible_chief,
    is_admin,
    owns_lock,
    staff_specialties,
)
from plannings.models import (
    Planning,
    PlanningAuditEvent,
    PlanningEditLock,
    PlanningVersion,
    PlanningVote,
)


class PlanningVoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanningVote
        fields = ["specialty_id", "specialty_name", "actor_id", "actor_name", "created_at"]


class PlanningVersionSerializer(serializers.ModelSerializer):
    votes = PlanningVoteSerializer(many=True)
    assignments = serializers.DictField(child=serializers.DictField())

    class Meta:
        model = PlanningVersion
        fields = [
            "number", "origin", "assignments", "changes", "actor_name", "reason", "urgent_surgery_id",
            "created_at", "applied_at", "votes",
        ]


class PlanningAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanningAuditEvent
        fields = ["id", "action", "actor_email", "surgery_id", "summary", "metadata", "created_at"]


class PlanningSerializer(serializers.ModelSerializer):
    current_version = PlanningVersionSerializer()
    applied_version = PlanningVersionSerializer()
    effective_assignments = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()

    def get_effective_assignments(self, obj):
        return effective_agenda(obj)

    def get_review(self, obj):
        lock = PlanningEditLock.objects.filter(planning=obj).select_related("actor").first()
        user = self.context["request"].user
        voted = set(obj.current_version.votes.values_list("designation", flat=True)) if obj.current_version else set()
        roster = chiefs() if obj.current_version_id and obj.operational else []
        approvals = [
            {
                "specialty_id": chief.specialty_id, "specialty_name": chief.specialty.nombre,
                "head_name": chief.user.nombre, "eligible": eligible_chief(chief),
                "voted": chief.designation in voted, "is_current_user": chief.user_id == user.pk,
            }
            for chief in roster
        ]
        editable = bool(obj.operational and obj.current_version_id)
        can_vote = any(item["is_current_user"] and item["eligible"] and not item["voted"] for item in approvals)
        return {
            "approvals": approvals,
            "lock": {
                "editor": lock.actor.nombre, "created_at": lock.created_at,
                "urgent": lock.urgent, "owned_by_session": owns_lock(lock, self.context["request"]),
            } if lock else None,
            "editable_specialty_ids": None if is_admin(user) else list(staff_specialties(user)),
            "can_vote": can_vote and obj.status == Planning.STATUS_PENDING_APPROVAL and not lock,
            "can_edit": editable and can_edit(user) and not lock,
            "can_adjust_urgent": editable and obj.status == Planning.STATUS_APPROVED and can_edit(user, urgent=True) and not lock,
            "can_recover": bool(lock and is_admin(user)),
        }

    class Meta:
        model = Planning
        fields = [
            "id", "scheduler_uuid", "week_start", "operational", "status", "input_payload",
            "output_payload", "error_message", "progress_percentage", "started_at", "finished_at",
            "duration_seconds", "approved_at", "approved_by", "rejected_at", "rejected_by",
            "rejection_reason", "created_at", "updated_at", "current_version", "applied_version",
            "effective_assignments", "review",
        ]


class PlanningCreateSerializer(serializers.Serializer):
    week_start = serializers.DateField()

    def validate_week_start(self, date):
        if date.weekday() != 0:
            raise serializers.ValidationError("La semana debe comenzar un lunes.")
        return date


class VersionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)


class AcquireSerializer(VersionSerializer):
    urgent = serializers.BooleanField(default=False)


class ReleaseSerializer(serializers.Serializer):
    lock_token = serializers.UUIDField()


class OperationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["assign", "move", "remove", "replace", "swap"])
    surgery_id = serializers.CharField(max_length=36)
    other_surgery_id = serializers.CharField(max_length=36, required=False)
    room_id = serializers.CharField(max_length=36, required=False)
    starts_at = serializers.DateTimeField(required=False)

    def validate(self, data):
        kind = data["kind"]
        if kind in {"assign", "move"} and not {"room_id", "starts_at"} <= data.keys():
            raise serializers.ValidationError("Indicá quirófano y hora de inicio.")
        if kind in {"replace", "swap"} and "other_surgery_id" not in data:
            raise serializers.ValidationError("Seleccioná la segunda cirugía.")
        if kind not in {"replace", "swap"} and "other_surgery_id" in data:
            raise serializers.ValidationError("Esta operación admite una sola cirugía.")
        return data


class EditSerializer(VersionSerializer, ReleaseSerializer):
    reason = serializers.CharField(allow_blank=True, default="", max_length=2000)
    operations = OperationSerializer(many=True, max_length=250)
    emergency = serializers.DictField(required=False)


class RecoverSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)
