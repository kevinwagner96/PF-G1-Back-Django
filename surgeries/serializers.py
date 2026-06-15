from rest_framework import serializers

from surgeries.models import MedicalStaff, OperatingRoom, Surgery


class SurgerySupplySerializer(serializers.Serializer):
    nombre = serializers.CharField(source="insumo.nombre")
    cantidad = serializers.IntegerField()


class SurgeryListSerializer(serializers.ModelSerializer):
    pacienteId = serializers.CharField(source="paciente_id")
    paciente = serializers.CharField(source="paciente.nombre")
    dni = serializers.CharField(source="paciente.dni")
    especialidad = serializers.CharField(source="especialidad.nombre")
    sala = serializers.CharField(source="sala.nombre", allow_null=True)
    anestesia = serializers.CharField(source="tipo_anestesia.nombre", allow_null=True)
    intervenciones = serializers.SerializerMethodField()
    insumos = SurgerySupplySerializer(many=True)

    class Meta:
        model = Surgery
        fields = [
            "id", "inicio", "fin", "pacienteId", "paciente", "dni", "especialidad", "sala",
            "anestesia", "byer", "sedacion", "estado", "intervenciones", "insumos", "observaciones",
        ]

    def get_intervenciones(self, obj):
        return [item.intervencion.nombre for item in obj.intervenciones.all()]


class PendingSurgerySerializer(serializers.ModelSerializer):
    specialty_id = serializers.CharField(source="especialidad_id")
    estimated_duration = serializers.IntegerField(source="duracion_estimada_minutos")
    clinical_priority = serializers.FloatField(source="prioridad_clinica")
    forced_surgeon_id = serializers.CharField(source="cirujano_forzado_id", allow_null=True)

    class Meta:
        model = Surgery
        fields = ["id", "specialty_id", "estimated_duration", "clinical_priority", "forced_surgeon_id"]


class OperatingRoomSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="nombre")
    or_type = serializers.CharField(source="tipo_quirofano")
    availability = serializers.JSONField(source="disponibilidad")

    class Meta:
        model = OperatingRoom
        fields = ["id", "name", "or_type", "availability"]


class MedicalStaffSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="nombre")
    role = serializers.CharField(source="rol")
    specialties_ids = serializers.SerializerMethodField()
    availability_hours = serializers.SerializerMethodField()

    class Meta:
        model = MedicalStaff
        fields = ["id", "name", "role", "specialties_ids", "availability_hours"]

    def get_specialties_ids(self, obj):
        return [specialty.id for specialty in obj.especialidades.all()]

    def get_availability_hours(self, obj):
        return {
            str(item.dia): [item.inicio_minutos, item.fin_minutos]
            for item in obj.disponibilidades.all()
        }
