from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.utils import timezone

from accounts.permissions import (
    ACCESS_SYSTEM_ADMIN_PERMISSION,
    APPROVE_PLANNING_PERMISSION,
    CREATE_PLANNING_PERMISSION,
)
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
GYNECOLOGY = "44444444-4444-4444-4444-444444444444"
OPHTHALMOLOGY = "55555555-5555-5555-5555-555555555555"
UROLOGY = "66666666-6666-6666-6666-666666666666"
ROOM_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
ROOM_2 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
ROOM_3 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3"
STAFF_1 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"
STAFF_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"
STAFF_3 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3"
STAFF_4 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb4"
STAFF_5 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb5"
STAFF_6 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb6"
PROC_TRAUMA = "99999999-9999-9999-9999-999999999901"
PROC_GENERAL = "99999999-9999-9999-9999-999999999902"
PROC_NEURO = "99999999-9999-9999-9999-999999999903"
PROC_GYNECOLOGY = "99999999-9999-9999-9999-999999999904"
PROC_OPHTHALMOLOGY = "99999999-9999-9999-9999-999999999905"
PROC_UROLOGY = "99999999-9999-9999-9999-999999999906"
ANESTHESIA = "77777777-7777-7777-7777-777777777701"
REPORT_VALIDATION_MARKER = "validation-report-duration"
REPORT_VALIDATION_PATIENT_PREFIX = "valrep-"
REPORT_VALIDATION_SURGERY_PREFIX = "valrep-surg-"

PATIENT_NAMES = [
    "Juan Martínez", "María Fernández", "Lucía Gómez", "Carlos Ruiz", "Ana López",
    "Pedro Sánchez", "Laura Fernández", "Roberto García", "Silvia Pérez", "Martín Díaz",
    "Claudia Moreno", "Diego Torres", "Patricia Vega", "Alejandro Ríos", "Natalia Castro",
    "Fernando Luna", "Gabriela Mendoza", "Oscar Navarro", "Verónica Herrera", "Sergio Romero",
    "Valentina Castro", "Nicolás Vera", "Micaela Sosa", "Federico Paz", "Carolina Suárez",
    "Hernán Acosta", "Sofía Núñez", "Tomás Molina", "Camila Pereyra", "Jorge Cabrera",
    "Rosa Acosta", "Miguel Benítez", "Paula Aguirre", "Esteban Molina", "Julia Barrios",
    "Iván Costa", "Mónica Ferreyra", "Raúl Méndez", "Héctor Domínguez", "Valeria Rojas",
    "Mariano Silva", "Florencia Ortiz", "Gonzalo Navarro", "Daniela Romero", "Emiliano Paz",
    "Agustina Vera", "Leandro Campos", "Cecilia Duarte", "Matías Correa", "Lorena Giménez",
    "Bruno Méndez", "Noelia Suárez", "Facundo Acosta", "Elena Figueroa", "Ramiro Soto",
    "Milagros Arias", "Pablo Benítez", "Rocío Molina", "Andrés Ferreyra", "Natalia Ríos",
]

SPECIALTY_DEFINITIONS = [
    (TRAUMA, "Traumatología", ["alta_complejidad"], PROC_TRAUMA, "Artroscopia de rodilla", STAFF_1, "Dr. Pérez"),
    (GENERAL, "Cirugía General", ["media_complejidad"], PROC_GENERAL, "Colecistectomía laparoscópica", STAFF_2, "Dra. Sosa"),
    (GYNECOLOGY, "Ginecología", ["media_complejidad"], PROC_GYNECOLOGY, "Histerectomía laparoscópica", STAFF_4, "Dra. Valentina Ruiz"),
    (NEURO, "Neurocirugía", ["alta_complejidad"], PROC_NEURO, "Descompresión lumbar", STAFF_3, "Dr. Gómez"),
    (OPHTHALMOLOGY, "Oftalmología", ["baja_complejidad"], PROC_OPHTHALMOLOGY, "Cirugía de cataratas", STAFF_5, "Dra. Paula Méndez"),
    (UROLOGY, "Urología", ["media_complejidad"], PROC_UROLOGY, "Resección transuretral", STAFF_6, "Dr. Nicolás Torres"),
]

REPORT_PATIENT_NAMES = [
    "Esteban Molina", "Rosa Acosta", "Miguel Benítez", "Camila Pereyra",
    "Jorge Cabrera", "Valentina Silva", "Héctor Domínguez", "Paula Aguirre",
    "Raúl Méndez", "Mónica Ferreyra", "Iván Costa", "Julia Barrios",
]


DEMO_GROUPS = {
    "System Admin": [ACCESS_SYSTEM_ADMIN_PERMISSION],
    "Administrador": [CREATE_PLANNING_PERMISSION, APPROVE_PLANNING_PERMISSION],
    "Cirujano": [APPROVE_PLANNING_PERMISSION],
    "Jefe Quirofano": [],
    "Recepcionista": [],
}


def sync_demo_groups_and_permissions() -> None:
    permissions_by_name = {
        f"{permission.content_type.app_label}.{permission.codename}": permission
        for permission in Permission.objects.filter(
            content_type__app_label__in=["accounts", "plannings"],
            codename__in=[
                "can_access_system_admin",
                "can_create_planning",
                "can_approve_planning",
            ],
        ).select_related("content_type")
    }
    for group_name, permission_names in DEMO_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(
            permission
            for permission_name in permission_names
            if (permission := permissions_by_name.get(permission_name)) is not None
        )


def seed_demo_data() -> None:
    User = get_user_model()
    with transaction.atomic():
        clear_report_validation_data()
        sync_demo_groups_and_permissions()
        demo_users = [
            ("sysadmin@hospital.com", "sysadmin123", {"username": "sysadmin@hospital.com", "nombre": "System Admin", "rol": "System Admin", "requiere_cambio_password": False, "bloqueado": False, "is_staff": True, "is_superuser": True}),
            ("admin@hospital.com", "admin123", {"username": "admin@hospital.com", "nombre": "Dr. Garcia", "rol": "Administrador", "requiere_cambio_password": False, "bloqueado": False, "is_staff": False, "is_superuser": False}),
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
            group_name = defaults["rol"]
            if group := Group.objects.filter(name=group_name).first():
                user.groups.set([group])

        for specialty_id, name, compatible_rooms, *_ in SPECIALTY_DEFINITIONS:
            Specialty.objects.update_or_create(
                id=specialty_id,
                defaults={
                    "nombre": name,
                    "estado": True,
                    "compatible_tipos_quirofano": compatible_rooms,
                    "min_bloques": 1,
                    "max_bloques": 3,
                },
            )

        OperatingRoom.objects.update_or_create(id=ROOM_1, defaults={"nombre": "Quirófano 1", "piso": "1", "disponible": True, "tipo_quirofano": "alta_complejidad", "disponibilidad": [[True, True], [True, True], [True, True], [True, True], [True, True]]})
        OperatingRoom.objects.update_or_create(id=ROOM_2, defaults={"nombre": "Quirófano 2", "piso": "1", "disponible": True, "tipo_quirofano": "media_complejidad", "disponibilidad": [[True, True], [True, True], [True, True], [True, True], [True, True]]})
        OperatingRoom.objects.update_or_create(id=ROOM_3, defaults={"nombre": "Quirófano 3", "piso": "2", "disponible": False, "tipo_quirofano": "baja_complejidad", "disponibilidad": [[True, False], [True, False], [True, False], [True, False], [True, False]]})

        for specialty_id, _name, _compatible_rooms, procedure_id, procedure_name, _staff_id, _staff_name in SPECIALTY_DEFINITIONS:
            Intervention.objects.update_or_create(
                id=procedure_id,
                defaults={
                    "nombre": procedure_name,
                    "descripcion": "Procedimiento demo para planificación IA",
                    "especialidad_id": specialty_id,
                    "estado": True,
                },
            )

        for _specialty_id, _name, _compatible_rooms, _procedure_id, _procedure_name, staff_id, staff_name in SPECIALTY_DEFINITIONS:
            MedicalStaff.objects.update_or_create(id=staff_id, defaults={"nombre": staff_name, "rol": "cirujano", "estado": True})
        for specialty_id, _name, _compatible_rooms, _procedure_id, _procedure_name, staff_id, _staff_name in SPECIALTY_DEFINITIONS:
            MedicalStaffSpecialty.objects.get_or_create(personal_medico_id=staff_id, especialidad_id=specialty_id)
        for _specialty_id, _name, _compatible_rooms, _procedure_id, _procedure_name, staff_id, _staff_name in SPECIALTY_DEFINITIONS:
            for day in range(5):
                MedicalStaffAvailability.objects.update_or_create(
                    personal_medico_id=staff_id,
                    dia=day,
                    create_defaults={
                        "id": f"cccccccc-cccc-cccc-cccc-{staff_id[-2:]}0000000{day}",
                        "inicio_minutos": 480,
                        "fin_minutos": 780,
                    },
                    defaults={"inicio_minutos": 480, "fin_minutos": 780},
                )

        AnesthesiaType.objects.update_or_create(id=ANESTHESIA, defaults={"nombre": "General", "descripcion": "Anestesia general", "estado": True})

        for index in range(1, 61):
            specialty_index = (index - 1) // 10
            specialty_id, _specialty_name, _compatible_rooms, intervention_id, _procedure_name, forced_staff, _staff_name = SPECIALTY_DEFINITIONS[specialty_index]
            name = PATIENT_NAMES[index - 1]
            Patient.objects.update_or_create(
                id=f"dddddddd-dddd-dddd-dddd-dddddddddd{index:02d}",
                defaults={"dni": f"401110{index:02d}", "nombre": name, "edad": 38 + index, "obra_social": ["OSDE", "PAMI", "Swiss Medical", "Galeno", "Medifé"][index % 5]},
            )
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
                    "prioridad_clinica": float(20 - ((index - 1) % 20)),
                    "cirujano_forzado_id": forced_staff,
                },
            )
            SurgeryIntervention.objects.update_or_create(
                cirugia_id=surgery_id,
                intervencion_id=intervention_id,
                defaults={"orden": 1},
            )

        seed_report_demo_data()


def clear_report_validation_data() -> tuple[int, int]:
    _, surgery_details = Surgery.objects.filter(
        id__startswith=REPORT_VALIDATION_SURGERY_PREFIX,
        observaciones__contains=REPORT_VALIDATION_MARKER,
    ).delete()
    _, patient_details = Patient.objects.filter(id__startswith=REPORT_VALIDATION_PATIENT_PREFIX).delete()
    deleted_surgeries = surgery_details.get("surgeries.Surgery", 0)
    deleted_patients = patient_details.get("surgeries.Patient", 0)
    return deleted_surgeries, deleted_patients


def make_report_datetime(day_offset: int, hour: int, minute: int = 0):
    day = timezone.localdate() + timedelta(days=day_offset)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def seed_report_demo_data() -> None:
    report_surgeries = [
        (-24, 8, 0, 120, "Completada", TRAUMA, PROC_TRAUMA, ROOM_1, STAFF_1, 11),
        (-22, 10, 30, 90, "Completada", GENERAL, PROC_GENERAL, ROOM_2, STAFF_2, 8),
        (-20, 13, 0, 150, "Cancelada", TRAUMA, PROC_TRAUMA, ROOM_1, STAFF_1, 16),
        (-18, 8, 30, 120, "Completada", GENERAL, PROC_GENERAL, ROOM_2, STAFF_2, 6),
        (-15, 11, 0, 180, "Programada", TRAUMA, PROC_TRAUMA, ROOM_1, STAFF_1, 13),
        (-12, 9, 0, 120, "Completada", GENERAL, PROC_GENERAL, ROOM_2, STAFF_2, 9),
        (-10, 14, 0, 90, "Cancelada", GENERAL, PROC_GENERAL, ROOM_2, STAFF_2, 7),
        (-8, 8, 0, 150, "Completada", TRAUMA, PROC_TRAUMA, ROOM_1, STAFF_1, 14),
        (-6, 10, 0, 120, "Programada", GENERAL, PROC_GENERAL, ROOM_2, STAFF_2, 5),
        (-4, 13, 30, 180, "Completada", TRAUMA, PROC_TRAUMA, ROOM_1, STAFF_1, 10),
        (-2, 9, 30, 90, "Programada", GENERAL, PROC_GENERAL, ROOM_2, STAFF_2, 4),
        (0, 12, 0, 120, "Programada", TRAUMA, PROC_TRAUMA, ROOM_1, STAFF_1, 6),
    ]

    for index, name in enumerate(REPORT_PATIENT_NAMES, start=1):
        patient_id = f"dddddddd-dddd-dddd-dddd-dddddddddd{index + 40:02d}"
        Patient.objects.update_or_create(
            id=patient_id,
            defaults={
                "dni": f"405550{index:02d}",
                "nombre": name,
                "edad": 45 + index,
                "obra_social": ["OSDE", "PAMI", "Swiss Medical", "Galeno"][index % 4],
            },
        )

        (
            day_offset,
            hour,
            minute,
            duration_minutes,
            surgery_status,
            specialty_id,
            intervention_id,
            room_id,
            staff_id,
            wait_days,
        ) = report_surgeries[index - 1]
        started_at = make_report_datetime(day_offset, hour, minute)
        finished_at = started_at + timedelta(minutes=duration_minutes)
        surgery_id = f"ffffffff-ffff-ffff-ffff-ffffffff{index:04d}"
        Surgery.objects.update_or_create(
            id=surgery_id,
            defaults={
                "paciente_id": patient_id,
                "especialidad_id": specialty_id,
                "sala_id": room_id,
                "tipo_anestesia_id": ANESTHESIA,
                "inicio": started_at,
                "fin": finished_at,
                "estado": surgery_status,
                "observaciones": "Caso demo histórico para reportes de indicadores",
                "duracion_estimada_minutos": duration_minutes,
                "prioridad_clinica": float(30 - index),
                "cirujano_forzado_id": staff_id,
            },
        )
        Surgery.objects.filter(id=surgery_id).update(
            created_at=started_at - timedelta(days=wait_days),
        )
        SurgeryIntervention.objects.update_or_create(
            cirugia_id=surgery_id,
            intervencion_id=intervention_id,
            defaults={"orden": 1},
        )


@transaction.atomic
def reset_demo_state() -> int:
    Planning.objects.all().delete()
    clear_report_validation_data()
    updated = Surgery.objects.update(estado="Pendiente", inicio=None, fin=None, sala=None)
    seed_demo_data()
    return updated
