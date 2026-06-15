from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class DemoUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "Datos PF-G1",
            {
                "fields": (
                    "nombre",
                    "rol",
                    "requiere_cambio_password",
                    "bloqueado",
                    "personal_id",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Datos PF-G1",
            {
                "fields": (
                    "email",
                    "nombre",
                    "rol",
                    "requiere_cambio_password",
                    "bloqueado",
                    "personal_id",
                )
            },
        ),
    )
    list_display = ("email", "nombre", "rol", "is_staff", "is_superuser", "bloqueado")
    list_filter = ("rol", "is_staff", "is_superuser", "bloqueado", "groups")
    search_fields = ("email", "nombre", "username")
    ordering = ("email",)
