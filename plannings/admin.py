from django.contrib import admin

from plannings.models import Planning


@admin.register(Planning)
class PlanningAdmin(admin.ModelAdmin):
    list_display = (
        "scheduler_uuid",
        "status",
        "progress_percentage",
        "duration_seconds",
        "approved_by",
        "created_at",
    )
    list_filter = ("status", "created_at", "approved_at")
    search_fields = ("scheduler_uuid", "approved_by", "error_message")
    readonly_fields = ("id", "scheduler_uuid", "created_at", "updated_at")
