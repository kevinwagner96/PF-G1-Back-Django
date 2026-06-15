from django.contrib import admin

from plannings.models import Planning, PlanningAuditEvent


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


@admin.register(PlanningAuditEvent)
class PlanningAuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "source", "planning", "surgery", "actor_email", "created_at")
    list_filter = ("action", "source", "created_at")
    search_fields = ("planning__scheduler_uuid", "actor_email", "summary")
    readonly_fields = (
        "id",
        "action",
        "planning",
        "surgery",
        "actor",
        "actor_email",
        "source",
        "summary",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
