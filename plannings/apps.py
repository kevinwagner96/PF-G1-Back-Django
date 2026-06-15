from django.apps import AppConfig


class PlanningsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plannings"

    def ready(self):
        from plannings.auditlog import register_auditlog_models

        register_auditlog_models()
