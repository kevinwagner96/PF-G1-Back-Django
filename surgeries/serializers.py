from rest_framework import serializers

from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    OperatingRoom,
    Patient,
    Specialty,
    Surgery,
    SurgeryIntervention,
)


class SurgerySupplySerializer(serializers.Serializer):
    nombre = serializers.CharField(source="insumo.nombre")
    cantidad = serializers.IntegerField()


class SurgeryListSerializer(serializers.ModelSerializer):
    pacienteId = serializers.CharField(source="paciente_id")
    paciente = serializers.CharField(source="paciente.nombre")
    dni = serializers.CharField(source="paciente.dni")
    edad = serializers.IntegerField(source="paciente.edad", allow_null=True)
    obra_social = serializers.CharField(source="paciente.obra_social", allow_null=True)
    especialidadId = serializers.CharField(source="especialidad_id")
    especialidad = serializers.CharField(source="especialidad.nombre")
    salaId = serializers.CharField(source="sala_id", allow_null=True)
    sala = serializers.CharField(source="sala.nombre", allow_null=True)
    anestesiaId = serializers.CharField(source="tipo_anestesia_id", allow_null=True)
    anestesia = serializers.CharField(source="tipo_anestesia.nombre", allow_null=True)
    intervencionIds = serializers.SerializerMethodField()
    intervenciones = serializers.SerializerMethodField()
    insumos = SurgerySupplySerializer(many=True)
    cirujanoForzadoId = serializers.CharField(source="cirujano_forzado_id", allow_null=True)
    cirujanoForzado = serializers.SerializerMethodField()
    duracion_estimada_minutos = serializers.IntegerField()
    prioridad_clinica = serializers.FloatField()

    class Meta:
        model = Surgery
        fields = [
            "id", "inicio", "fin", "pacienteId", "paciente", "dni", "edad", "obra_social",
            "especialidadId", "especialidad", "salaId", "sala", "anestesiaId", "anestesia",
            "byer", "sedacion", "estado", "intervencionIds", "intervenciones", "insumos",
            "observaciones", "duracion_estimada_minutos", "prioridad_clinica", "cirujanoForzadoId",
            "cirujanoForzado", "created_at", "updated_at",
        ]

    def get_intervencionIds(self, obj):
        return [item.intervencion_id for item in obj.intervenciones.all()]

    def get_intervenciones(self, obj):
        return [item.intervencion.nombre for item in obj.intervenciones.all()]

    def get_cirujanoForzado(self, obj):
        if obj.cirujano_forzado is None:
            return None
        return {
            "id": obj.cirujano_forzado.id,
            "nombre": obj.cirujano_forzado.nombre,
            "rol": obj.cirujano_forzado.rol,
        }


class PatientInlineSerializer(serializers.Serializer):
    dni = serializers.CharField(max_length=20, trim_whitespace=True)
    nombre = serializers.CharField(max_length=255, trim_whitespace=True)
    edad = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    obra_social = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=120, trim_whitespace=True)


class SurgeryWriteSerializer(serializers.Serializer):
    patient = PatientInlineSerializer()
    intervention_ids = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
    )
    tipo_anestesia_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cirujano_forzado_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    byer = serializers.BooleanField(required=False, default=False)
    sedacion = serializers.BooleanField(required=False, default=False)
    observaciones = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    duracion_estimada_minutos = serializers.IntegerField(min_value=1)
    prioridad_clinica = serializers.FloatField(min_value=0.000001)

    def validate_intervention_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("No se pueden repetir intervenciones")
        interventions = list(Intervention.objects.filter(id__in=value).select_related("especialidad"))
        if len(interventions) != len(value):
            raise serializers.ValidationError("Una o más intervenciones no existen")
        inactive = [intervention.nombre for intervention in interventions if not intervention.estado]
        if inactive:
            raise serializers.ValidationError(f"Intervenciones inactivas: {', '.join(inactive)}")
        specialty_ids = {intervention.especialidad_id for intervention in interventions}
        if None in specialty_ids or len(specialty_ids) != 1:
            raise serializers.ValidationError("Todas las intervenciones deben pertenecer a una misma especialidad activa")
        specialty = interventions[0].especialidad
        if specialty is None or not specialty.estado:
            raise serializers.ValidationError("La especialidad de la intervención no está activa")
        self.context["interventions"] = interventions
        self.context["specialty"] = specialty
        return value

    def validate_tipo_anestesia_id(self, value):
        if not value:
            return None
        if not AnesthesiaType.objects.filter(id=value, estado=True).exists():
            raise serializers.ValidationError("El tipo de anestesia no existe o está inactivo")
        return value

    def validate_cirujano_forzado_id(self, value):
        if not value:
            return None
        staff = MedicalStaff.objects.filter(id=value, estado=True).first()
        if staff is None or staff.rol.lower() != "cirujano":
            raise serializers.ValidationError("El cirujano no existe, está inactivo o no tiene rol cirujano")
        return value

    def save(self, **kwargs):
        patient_data = self.validated_data["patient"]
        patient, _ = Patient.objects.update_or_create(
            dni=patient_data["dni"],
            defaults={
                "nombre": patient_data["nombre"],
                "edad": patient_data.get("edad"),
                "obra_social": patient_data.get("obra_social") or None,
            },
        )
        interventions = self.context["interventions"]
        specialty = self.context["specialty"]
        surgery = self.instance or Surgery()
        surgery.paciente = patient
        surgery.especialidad = specialty
        surgery.tipo_anestesia_id = self.validated_data.get("tipo_anestesia_id")
        surgery.cirujano_forzado_id = self.validated_data.get("cirujano_forzado_id")
        surgery.byer = self.validated_data.get("byer", False)
        surgery.sedacion = self.validated_data.get("sedacion", False)
        surgery.observaciones = self.validated_data.get("observaciones") or None
        surgery.duracion_estimada_minutos = self.validated_data["duracion_estimada_minutos"]
        surgery.prioridad_clinica = self.validated_data["prioridad_clinica"]
        if surgery.pk is None:
            surgery.estado = "Pendiente"
        surgery.save()
        SurgeryIntervention.objects.filter(cirugia=surgery).exclude(
            intervencion_id__in=[intervention.id for intervention in interventions],
        ).delete()
        for index, intervention in enumerate(interventions, start=1):
            SurgeryIntervention.objects.update_or_create(
                cirugia=surgery,
                intervencion=intervention,
                defaults={"orden": index},
            )
        return surgery


class SpecialtyCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = Specialty
        fields = ["id", "nombre"]


class InterventionCatalogSerializer(serializers.ModelSerializer):
    especialidadId = serializers.CharField(source="especialidad_id")

    class Meta:
        model = Intervention
        fields = ["id", "nombre", "especialidadId"]


class AnesthesiaTypeCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnesthesiaType
        fields = ["id", "nombre"]


class MedicalStaffCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalStaff
        fields = ["id", "nombre", "rol"]


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
