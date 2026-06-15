from django.contrib import admin

from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    MedicalStaffAvailability,
    MedicalStaffSpecialty,
    OperatingRoom,
    Patient,
    Specialty,
    Supply,
    Surgery,
    SurgeryIntervention,
    SurgerySupply,
)


class SurgeryInterventionInline(admin.TabularInline):
    model = SurgeryIntervention
    extra = 0


class SurgerySupplyInline(admin.TabularInline):
    model = SurgerySupply
    extra = 0


class MedicalStaffSpecialtyInline(admin.TabularInline):
    model = MedicalStaffSpecialty
    extra = 0


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("nombre", "dni", "edad", "obra_social")
    search_fields = ("nombre", "dni", "obra_social")


@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ("nombre", "estado", "min_bloques", "max_bloques")
    list_filter = ("estado",)
    search_fields = ("nombre",)


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "especialidad", "estado")
    list_filter = ("estado", "especialidad")
    search_fields = ("nombre", "especialidad__nombre")


@admin.register(OperatingRoom)
class OperatingRoomAdmin(admin.ModelAdmin):
    list_display = ("nombre", "piso", "disponible", "tipo_quirofano")
    list_filter = ("disponible", "tipo_quirofano")
    search_fields = ("nombre", "piso")


@admin.register(MedicalStaff)
class MedicalStaffAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rol", "estado")
    list_filter = ("rol", "estado", "especialidades")
    search_fields = ("nombre",)
    inlines = (MedicalStaffSpecialtyInline,)


@admin.register(MedicalStaffAvailability)
class MedicalStaffAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("personal_medico", "dia", "inicio_minutos", "fin_minutos")
    list_filter = ("dia", "personal_medico")


@admin.register(AnesthesiaType)
class AnesthesiaTypeAdmin(admin.ModelAdmin):
    list_display = ("nombre", "estado")
    list_filter = ("estado",)
    search_fields = ("nombre",)


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ("nombre", "stock")
    search_fields = ("nombre",)


@admin.register(Surgery)
class SurgeryAdmin(admin.ModelAdmin):
    list_display = ("paciente", "especialidad", "estado", "sala", "inicio", "fin")
    list_filter = ("estado", "especialidad", "sala")
    search_fields = ("paciente__nombre", "paciente__dni", "especialidad__nombre")
    inlines = (SurgeryInterventionInline, SurgerySupplyInline)


admin.site.register(SurgeryIntervention)
admin.site.register(SurgerySupply)
