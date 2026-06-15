from django.contrib.auth import get_user_model
from django.db import transaction

from plannings.models import Planning
from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    MedicalStaffAvailability,
    MedicalStaffSpecialty,
    OperatingRoom,
    Patient,
    Specialty,
    Surgery,
    SurgeryIntervention,
)

TRAUMA = "11111111-1111-1111-1111-111111111111"
GENERAL = "22222222-2222-2222-2222-222222222222"
NEURO = "33333333-3333-3333-3333-333333333333"
ROOM_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
ROOM_2 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
ROOM_3 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3"
STAFF_1 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"
STAFF_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"
STAFF_3 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3"
PROC_TRAUMA = "99999999-9999-9999-9999-999999999901"
PROC_GENERAL = "99999999-9999-9999-9999-999999999902"
PROC_NEURO = "99999999-9999-9999-9999-999999999903"
ANESTHESIA = "77777777-7777-7777-7777-777777777701"

PATIENT_NAMES = [
    "Juan Martínez", "María Fernández", "Lucía Gómez", "Carlos Ruiz", "Ana López",
    "Pedro Sánchez", "Laura Fernández", "Roberto García", "Silvia Pérez", "Martín Díaz",
    "Claudia Moreno", "Diego Torres", "Patricia Vega", "Alejandro Ríos", "Natalia Castro",
    "Fernando Luna", "Gabriela Mendoza", "Oscar Navarro", "Verónica Herrera", "Sergio Romero",
]


def seed_demo_data() -> None:
    User = get_user_model()
    with transaction.atomic():
        demo_users = [
            ("admin@hospital.com", "admin123", {"username": "admin@hospital.com", "nombre": "Dr. Garcia", "rol": "Administrador", "requiere_cambio_password": False, "bloqueado": False, "is_staff": True, "is_superuser": True}),
            ("cirujano@hospital.com", "cirujano123", {"username": "cirujano@hospital.com", "nombre": "Dr. Lopez", "rol": "Cirujano", "requiere_cambio_password": False, "bloqueado": False, "personal_id": STAFF_1}),
            ("jefe@hospital.com", "jefe123", {"username": "jefe@hospital.com", "nombre": "Dra. Martinez", "rol": "Jefe Quirofano", "requiere_cambio_password": False, "bloqueado": False}),
            ("recepcion@hospital.com", "recepcion123", {"username": "recepcion@hospital.com", "nombre": "Maria Sanchez", "rol": "Recepcionista", "requiere_cambio_password": False, "bloqueado": False}),
            ("bloqueado@hospital.com", "blocked123", {"username": "bloqueado@hospital.com", "nombre": "Dr. Bloqueado", "rol": "Cirujano", "requiere_cambio_password": False, "bloqueado": True}),
        ]
        for email, password, defaults in demo_users:
            user, created = User.objects.update_or_create(email=email, defaults=defaults)
            if created or not user.has_usable_password():
                user.set_password(password)
                user.save(update_fields=["password"])

        Specialty.objects.update_or_create(id=TRAUMA, defaults={"nombre": "Traumatología", "estado": True, "compatible_tipos_quirofano": ["alta_complejidad"], "min_bloques": 4, "max_bloques": 4})
        Specialty.objects.update_or_create(id=GENERAL, defaults={"nombre": "Cirugía General", "estado": True, "compatible_tipos_quirofano": ["media_complejidad"], "min_bloques": 4, "max_bloques": 4})
        Specialty.objects.update_or_create(id=NEURO, defaults={"nombre": "Neurología", "estado": False, "compatible_tipos_quirofano": ["alta_complejidad"], "min_bloques": 2, "max_bloques": 4})

        OperatingRoom.objects.update_or_create(id=ROOM_1, defaults={"nombre": "Quirófano 1", "piso": "1", "disponible": True, "tipo_quirofano": "alta_complejidad", "disponibilidad": [[True, True], [True, True], [True, True], [True, True], [True, True]]})
        OperatingRoom.objects.update_or_create(id=ROOM_2, defaults={"nombre": "Quirófano 2", "piso": "1", "disponible": True, "tipo_quirofano": "media_complejidad", "disponibilidad": [[True, True], [True, True], [True, True], [True, True], [True, True]]})
        OperatingRoom.objects.update_or_create(id=ROOM_3, defaults={"nombre": "Quirófano 3", "piso": "2", "disponible": False, "tipo_quirofano": "baja_complejidad", "disponibilidad": [[True, False], [True, False], [True, False], [True, False], [True, False]]})

        Intervention.objects.update_or_create(id=PROC_TRAUMA, defaults={"nombre": "Artroscopia de rodilla", "descripcion": "Procedimiento demo para planificación IA", "especialidad_id": TRAUMA, "estado": True})
        Intervention.objects.update_or_create(id=PROC_GENERAL, defaults={"nombre": "Colecistectomía laparoscópica", "descripcion": "Procedimiento demo para planificación IA", "especialidad_id": GENERAL, "estado": True})
        Intervention.objects.update_or_create(id=PROC_NEURO, defaults={"nombre": "Descompresión lumbar", "descripcion": "Procedimiento demo para planificación IA", "especialidad_id": NEURO, "estado": True})

        MedicalStaff.objects.update_or_create(id=STAFF_1, defaults={"nombre": "Dr. Pérez", "rol": "cirujano", "estado": True})
        MedicalStaff.objects.update_or_create(id=STAFF_2, defaults={"nombre": "Dra. Sosa", "rol": "cirujano", "estado": True})
        MedicalStaff.objects.update_or_create(id=STAFF_3, defaults={"nombre": "Dr. Gómez", "rol": "cirujano", "estado": True})
        for staff_id, specialty_id in [(STAFF_1, TRAUMA), (STAFF_2, GENERAL), (STAFF_3, NEURO)]:
            MedicalStaffSpecialty.objects.get_or_create(personal_medico_id=staff_id, especialidad_id=specialty_id)
        for staff_id in [STAFF_1, STAFF_2]:
            for day in range(5):
                MedicalStaffAvailability.objects.update_or_create(
                    personal_medico_id=staff_id,
                    dia=day,
                    defaults={"id": f"cccccccc-cccc-cccc-cccc-{staff_id[-2:]}0000000{day}", "inicio_minutos": 480, "fin_minutos": 1020},
                )

        AnesthesiaType.objects.update_or_create(id=ANESTHESIA, defaults={"nombre": "General", "descripcion": "Anestesia general", "estado": True})

        for index, name in enumerate(PATIENT_NAMES, start=1):
            Patient.objects.update_or_create(
                id=f"dddddddd-dddd-dddd-dddd-dddddddddd{index:02d}",
                defaults={"dni": f"401110{index:02d}", "nombre": name, "edad": 38 + index, "obra_social": ["OSDE", "PAMI", "Swiss Medical", "Galeno", "Medifé"][index % 5]},
            )
            specialty_id = TRAUMA if index <= 10 else GENERAL
            forced_staff = STAFF_1 if index <= 10 else STAFF_2
            intervention_id = PROC_TRAUMA if index <= 10 else PROC_GENERAL
            surgery_id = f"eeeeeeee-eeee-eeee-eeee-eeeeeeeeee{index:02d}"
            Surgery.objects.update_or_create(
                id=surgery_id,
                defaults={
                    "paciente_id": f"dddddddd-dddd-dddd-dddd-dddddddddd{index:02d}",
                    "especialidad_id": specialty_id,
                    "sala": None,
                    "tipo_anestesia_id": ANESTHESIA,
                    "inicio": None,
                    "fin": None,
                    "estado": "Pendiente",
                    "observaciones": "Caso demo ampliado para planificación IA",
                    "duracion_estimada_minutos": 180 if index % 3 == 0 else 120,
                    "prioridad_clinica": float(21 - index),
                    "cirujano_forzado_id": forced_staff,
                },
            )
            SurgeryIntervention.objects.update_or_create(
                cirugia_id=surgery_id,
                intervencion_id=intervention_id,
                defaults={"orden": 1},
            )


def reset_demo_state() -> int:
    Planning.objects.all().delete()
    updated = Surgery.objects.update(estado="Pendiente", inicio=None, fin=None, sala=None)
    seed_demo_data()
    return updated
