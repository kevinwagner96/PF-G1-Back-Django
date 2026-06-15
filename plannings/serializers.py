from rest_framework import serializers

from plannings.models import Planning


class PlanningSerializer(serializers.ModelSerializer):
    class Meta:
        model = Planning
        fields = [
            "id", "scheduler_uuid", "status", "input_payload", "output_payload", "error_message",
            "progress_percentage", "started_at", "finished_at", "duration_seconds", "approved_at",
            "approved_by", "created_at", "updated_at",
        ]


class PlanningCreateSerializer(serializers.Serializer):
    week_start = serializers.DateField()
