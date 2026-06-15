import uuid

from django.db import models


def new_uuid() -> str:
    return str(uuid.uuid4())


class Patient(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    dni = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=255)
    edad = models.IntegerField(null=True, blank=True)
    obra_social = models.CharField(max_length=120, null=True, blank=True)

    class Meta:
        ordering = ["nombre"]


class Specialty(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    nombre = models.CharField(max_length=120, unique=True)
    estado = models.BooleanField(default=True)
    compatible_tipos_quirofano = models.JSONField(default=list)
    min_bloques = models.IntegerField(default=1)
    max_bloques = models.IntegerField(default=10)

    class Meta:
        ordering = ["nombre"]


class Intervention(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    nombre = models.CharField(max_length=180)
    descripcion = models.TextField(null=True, blank=True)
    especialidad = models.ForeignKey(Specialty, null=True, blank=True, on_delete=models.SET_NULL, related_name="intervenciones")
    estado = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["nombre", "especialidad"], name="uniq_intervention_specialty")]
        ordering = ["nombre"]


class OperatingRoom(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    nombre = models.CharField(max_length=120, unique=True)
    piso = models.CharField(max_length=30, null=True, blank=True)
    disponible = models.BooleanField(default=True)
    tipo_quirofano = models.CharField(max_length=40, default="media_complejidad")
    disponibilidad = models.JSONField(default=list)

    class Meta:
        ordering = ["nombre"]


class MedicalStaff(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    nombre = models.CharField(max_length=255)
    rol = models.CharField(max_length=40)
    estado = models.BooleanField(default=True)
    especialidades = models.ManyToManyField(Specialty, through="MedicalStaffSpecialty", related_name="personal_medico")

    class Meta:
        ordering = ["nombre"]


class MedicalStaffSpecialty(models.Model):
    personal_medico = models.ForeignKey(MedicalStaff, on_delete=models.CASCADE)
    especialidad = models.ForeignKey(Specialty, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["personal_medico", "especialidad"], name="uniq_staff_specialty")]


class MedicalStaffAvailability(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    personal_medico = models.ForeignKey(MedicalStaff, on_delete=models.CASCADE, related_name="disponibilidades")
    dia = models.IntegerField()
    inicio_minutos = models.IntegerField()
    fin_minutos = models.IntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["personal_medico", "dia"], name="uniq_staff_day")]
        ordering = ["dia"]


class AnesthesiaType(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.TextField(null=True, blank=True)
    estado = models.BooleanField(default=True)


class Supply(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    nombre = models.CharField(max_length=180, unique=True)
    stock = models.IntegerField(default=0)


class Surgery(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    inicio = models.DateTimeField(null=True, blank=True, db_index=True)
    fin = models.DateTimeField(null=True, blank=True)
    paciente = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="cirugias")
    especialidad = models.ForeignKey(Specialty, on_delete=models.CASCADE, related_name="cirugias")
    sala = models.ForeignKey(OperatingRoom, null=True, blank=True, on_delete=models.SET_NULL, related_name="cirugias")
    tipo_anestesia = models.ForeignKey(AnesthesiaType, null=True, blank=True, on_delete=models.SET_NULL, related_name="cirugias")
    byer = models.BooleanField(default=False)
    sedacion = models.BooleanField(default=False)
    estado = models.CharField(max_length=40, default="Pendiente", db_index=True)
    observaciones = models.TextField(null=True, blank=True)
    duracion_estimada_minutos = models.IntegerField(default=60)
    prioridad_clinica = models.FloatField(default=1.0)
    cirujano_forzado = models.ForeignKey(MedicalStaff, null=True, blank=True, on_delete=models.SET_NULL, related_name="cirugias_forzadas")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [models.F("inicio").asc(nulls_last=True), "-created_at"]


class SurgeryIntervention(models.Model):
    cirugia = models.ForeignKey(Surgery, on_delete=models.CASCADE, related_name="intervenciones")
    intervencion = models.ForeignKey(Intervention, on_delete=models.CASCADE, related_name="cirugias")
    orden = models.IntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cirugia", "intervencion"], name="uniq_surgery_intervention")]
        ordering = ["orden"]


class SurgerySupply(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=new_uuid)
    cirugia = models.ForeignKey(Surgery, on_delete=models.CASCADE, related_name="insumos")
    insumo = models.ForeignKey(Supply, on_delete=models.CASCADE, related_name="lineas_cirugia")
    cantidad = models.IntegerField()
    observaciones = models.TextField(null=True, blank=True)
