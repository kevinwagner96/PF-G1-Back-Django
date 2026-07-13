from calendar import monthrange
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from demo.seed import (
    REPORT_VALIDATION_MARKER,
    clear_report_validation_data,
    seed_demo_data,
)
from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    OperatingRoom,
    Patient,
    Surgery,
    SurgeryIntervention,
)

class Command(BaseCommand):
    help = "Seed deterministic scheduled surgeries for report duration validation."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--surgeries-per-month", type=int, default=500)
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete validation surgeries and patients without creating new validation data.",
        )

    def handle(self, *args, **options):
        year = options["year"]
        surgeries_per_month = options["surgeries_per_month"]
        if surgeries_per_month < 1:
            raise CommandError("--surgeries-per-month must be greater than zero")

        with transaction.atomic():
            if options["clear"]:
                deleted_surgeries, deleted_patients = clear_report_validation_data()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deleted {deleted_surgeries} validation surgeries and "
                        f"{deleted_patients} validation patients."
                    )
                )
                return

            seed_demo_data()
            resources = self._load_resources()
            total = 0
            for month in range(1, 13):
                total += self._seed_month(
                    year=year,
                    month=month,
                    surgeries_per_month=surgeries_per_month,
                    resources=resources,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {total} validation surgeries for {year} "
                f"({surgeries_per_month} per month)."
            )
        )

    def _load_resources(self):
        rooms = list(OperatingRoom.objects.filter(disponible=True).order_by("nombre"))
        interventions = list(
            Intervention.objects.filter(estado=True, especialidad__estado=True)
            .select_related("especialidad")
            .order_by("nombre")
        )
        anesthesia = AnesthesiaType.objects.filter(estado=True).order_by("nombre").first()
        surgeons = list(MedicalStaff.objects.filter(estado=True, rol__iexact="cirujano").order_by("nombre"))

        if not rooms:
            raise CommandError("No available operating rooms found")
        if not interventions:
            raise CommandError("No active interventions found")
        if anesthesia is None:
            raise CommandError("No active anesthesia type found")
        if not surgeons:
            raise CommandError("No active surgeons found")

        return {
            "rooms": rooms,
            "interventions": interventions,
            "anesthesia": anesthesia,
            "surgeons": surgeons,
        }

    def _seed_month(self, *, year, month, surgeries_per_month, resources):
        days_in_month = monthrange(year, month)[1]
        created_or_updated = 0

        for index in range(surgeries_per_month):
            day = (index % days_in_month) + 1
            slot = index // days_in_month
            hour = 7 + (slot % 11)
            minute = 0 if (slot // 11) % 2 == 0 else 30
            duration_minutes = [60, 90, 120, 150][index % 4]
            started_at = timezone.make_aware(datetime.combine(date(year, month, day), time(hour, minute)))
            finished_at = started_at + timedelta(minutes=duration_minutes)
            wait_days = 3 + (index % 28)

            intervention = resources["interventions"][index % len(resources["interventions"])]
            room = resources["rooms"][index % len(resources["rooms"])]
            surgeon = resources["surgeons"][index % len(resources["surgeons"])]
            status = self._status_for_index(index)
            sequence = ((month - 1) * surgeries_per_month) + index + 1
            patient_id = f"valrep-{year}-{sequence:08d}"
            surgery_id = f"valrep-surg-{year}-{sequence:08d}"

            Patient.objects.update_or_create(
                id=patient_id,
                defaults={
                    "dni": f"VR{year}{sequence:08d}"[-20:],
                    "nombre": f"Paciente Validacion Reporte {sequence:05d}",
                    "edad": 25 + (index % 55),
                    "obra_social": ["OSDE", "PAMI", "Swiss Medical", "Galeno", "Medife"][index % 5],
                },
            )

            Surgery.objects.update_or_create(
                id=surgery_id,
                defaults={
                    "inicio": started_at,
                    "fin": finished_at,
                    "paciente_id": patient_id,
                    "especialidad": intervention.especialidad,
                    "sala": room,
                    "tipo_anestesia": resources["anesthesia"],
                    "byer": index % 9 == 0,
                    "sedacion": index % 7 == 0,
                    "estado": status,
                    "observaciones": f"{REPORT_VALIDATION_MARKER}; year={year}; month={month:02d}",
                    "duracion_estimada_minutos": duration_minutes,
                    "prioridad_clinica": float(1 + (index % 10)),
                    "cirujano_forzado": surgeon,
                },
            )
            Surgery.objects.filter(id=surgery_id).update(created_at=started_at - timedelta(days=wait_days))
            SurgeryIntervention.objects.update_or_create(
                cirugia_id=surgery_id,
                intervencion=intervention,
                defaults={"orden": 1},
            )
            created_or_updated += 1

        return created_or_updated

    @staticmethod
    def _status_for_index(index):
        position = index % 20
        if position == 0:
            return "Cancelada"
        if position in {1, 2}:
            return "Programada"
        return "Completada"
