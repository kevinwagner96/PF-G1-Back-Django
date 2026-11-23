from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CREATE_PLANNING_PERMISSION, has_explicit_permission
from plannings.agenda import Conflict, audit, effective_agenda
from plannings.models import AppliedSurgery, Planning, PlanningAuditEvent, PlanningEditLock
from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    MedicalStaffAvailability,
    OperatingRoom,
    Specialty,
    Supply,
    Surgery,
    SurgeryCancellation,
)
from surgeries.serializers import (
    AnesthesiaTypeCatalogSerializer,
    InterventionCatalogSerializer,
    MedicalStaffAvailabilityWriteSerializer,
    MedicalStaffCatalogSerializer,
    MedicalStaffSerializer,
    OperatingRoomSerializer,
    PendingSurgerySerializer,
    SpecialtyCatalogSerializer,
    SurgeryListSerializer,
    SurgeryWriteSerializer,
)


def surgery_queryset():
    return Surgery.objects.select_related(
        "paciente", "especialidad", "sala", "tipo_anestesia", "cirujano_forzado", "cancellation"
    ).prefetch_related("intervenciones__intervencion", "insumos__insumo")


def has_active_planning() -> bool:
    return Planning.objects.filter(operational=True, status__in=Planning.ACTIVE_STATUSES).exists()


def ensure_not_in_review(surgery_id):
    relevant = Planning.objects.filter(operational=True, status__in=Planning.ACTIVE_STATUSES)
    for planning in relevant.select_related("current_version"):
        if planning.status == Planning.STATUS_PLANNING:
            blocked = surgery_id in planning.input_payload.get("id_maps", {}).get("surgeries", {})
        else:
            blocked = surgery_id in (planning.current_version.assignments if planning.current_version else {})
        if blocked:
            raise Conflict("La cirugía forma parte de una generación o revisión activa.")


def require_surgery_management_permission(request):
    return has_explicit_permission(request.user, CREATE_PLANNING_PERMISSION)


class SurgeryListView(APIView):
    def get(self, request):
        return Response(SurgeryListSerializer(surgery_queryset(), many=True).data)

    @transaction.atomic
    def post(self, request):
        if not require_surgery_management_permission(request):
            return Response({"detail": "No tiene permiso para gestionar cirugías"}, status=status.HTTP_403_FORBIDDEN)
        serializer = SurgeryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        surgery = serializer.save()
        return Response(SurgeryListSerializer(surgery_queryset().get(id=surgery.id)).data, status=status.HTTP_201_CREATED)


class SurgeryDetailView(APIView):
    def get_object(self, surgery_id: str) -> Surgery | None:
        return surgery_queryset().filter(id=surgery_id).first()

    def get(self, request, surgery_id: str):
        surgery = self.get_object(surgery_id)
        if surgery is None:
            return Response({"detail": "Surgery not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(SurgeryListSerializer(surgery).data)

    @transaction.atomic
    def patch(self, request, surgery_id: str):
        if not require_surgery_management_permission(request):
            return Response({"detail": "No tiene permiso para gestionar cirugías"}, status=status.HTTP_403_FORBIDDEN)
        surgery = Surgery.objects.select_for_update().filter(id=surgery_id).first()
        if surgery is None:
            return Response({"detail": "Surgery not found"}, status=status.HTTP_404_NOT_FOUND)
        if surgery.estado != "Pendiente":
            return Response({"detail": "Solo se pueden editar cirugías pendientes"}, status=status.HTTP_400_BAD_REQUEST)
        ensure_not_in_review(surgery_id)

        serializer = SurgeryWriteSerializer(instance=surgery, data=request.data)
        serializer.is_valid(raise_exception=True)
        surgery = serializer.save()
        return Response(SurgeryListSerializer(surgery_queryset().get(id=surgery.id)).data)


class SurgeryCancelView(APIView):
    @transaction.atomic
    def post(self, request, surgery_id: str):
        if not require_surgery_management_permission(request):
            return Response({"detail": "No tiene permiso para gestionar cirugías"}, status=status.HTTP_403_FORBIDDEN)
        reason = request.data.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValidationError({"detail": "Indicá el motivo de la cancelación."})
        planning_id = AppliedSurgery.objects.filter(surgery_id=surgery_id).values_list("planning_id", flat=True).first()
        planning = Planning.objects.select_for_update().filter(pk=planning_id).first() if planning_id else None
        if planning and PlanningEditLock.objects.filter(planning=planning).exists():
            raise Conflict("La agenda de la cirugía está en edición.")
        surgery = Surgery.objects.select_for_update().filter(id=surgery_id).first()
        if AppliedSurgery.objects.filter(surgery_id=surgery_id).exclude(planning_id=planning_id).exists():
            raise Conflict("La asignación cambió. Volvé a cargar la cirugía.")
        if surgery is None:
            return Response({"detail": "Surgery not found"}, status=status.HTTP_404_NOT_FOUND)
        if surgery.estado not in {"Pendiente", "Programada"}:
            return Response({"detail": "Solo se pueden cancelar cirugías pendientes o programadas"}, status=status.HTTP_400_BAD_REQUEST)
        ensure_not_in_review(surgery_id)

        SurgeryCancellation.objects.create(surgery=surgery, reason=reason.strip(), scheduled_start=surgery.inicio)
        if planning:
            audit(
                planning, PlanningAuditEvent.Action.SURGERY_CANCELLED, "Cirugía cancelada",
                actor=request.user, surgery=surgery,
                metadata={"reason": reason.strip(), "before": effective_agenda(planning).get(surgery_id), "after": None},
            )
            AppliedSurgery.objects.filter(planning=planning, surgery=surgery).delete()
        surgery.estado = "Cancelada"
        surgery.inicio = None
        surgery.fin = None
        surgery.sala = None
        surgery.save(update_fields=["estado", "inicio", "fin", "sala", "updated_at"])
        return Response(SurgeryListSerializer(surgery_queryset().get(id=surgery.id)).data)


class PendingSurgeryListView(APIView):
    def get(self, request):
        surgeries = surgery_queryset().filter(estado="Pendiente").order_by("-prioridad_clinica", "created_at")
        return Response(PendingSurgerySerializer(surgeries, many=True).data)


class OperatingRoomListView(APIView):
    def get(self, request):
        rooms = OperatingRoom.objects.filter(disponible=True).order_by("nombre")
        return Response(OperatingRoomSerializer(rooms, many=True).data)


class MedicalStaffListView(APIView):
    def get(self, request):
        staff = MedicalStaff.objects.filter(estado=True).prefetch_related("especialidades", "disponibilidades").order_by("nombre")
        return Response(MedicalStaffSerializer(staff, many=True).data)


class MedicalStaffAvailabilityView(APIView):
    @transaction.atomic
    def put(self, request, staff_id: str):
        if not require_surgery_management_permission(request):
            return Response(
                {"detail": "No tiene permiso para gestionar horarios médicos"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if has_active_planning():
            return Response(
                {"detail": "No se pueden modificar horarios mientras hay una planificación activa"},
                status=status.HTTP_409_CONFLICT,
            )
        staff = MedicalStaff.objects.filter(id=staff_id, estado=True, rol__iexact="cirujano").first()
        if staff is None:
            return Response({"detail": "Cirujano no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        serializer = MedicalStaffAvailabilityWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff.disponibilidades.all().delete()
        MedicalStaffAvailability.objects.bulk_create(
            MedicalStaffAvailability(
                personal_medico=staff,
                dia=day,
                inicio_minutos=hours[0],
                fin_minutos=hours[1],
            )
            for day, hours in sorted(serializer.validated_data["availability_hours"].items())
        )
        updated = MedicalStaff.objects.prefetch_related("especialidades", "disponibilidades").get(id=staff.id)
        return Response(MedicalStaffSerializer(updated).data)


class SurgeryCatalogsView(APIView):
    def get(self, request):
        return Response(
            {
                "specialties": SpecialtyCatalogSerializer(Specialty.objects.filter(estado=True).order_by("nombre"), many=True).data,
                "interventions": InterventionCatalogSerializer(
                    Intervention.objects.filter(estado=True, especialidad__estado=True).select_related("especialidad").order_by("nombre"),
                    many=True,
                ).data,
                "anesthesia_types": AnesthesiaTypeCatalogSerializer(AnesthesiaType.objects.filter(estado=True).order_by("nombre"), many=True).data,
                "surgeons": MedicalStaffCatalogSerializer(
                    MedicalStaff.objects.filter(estado=True, rol__iexact="cirujano")
                    .prefetch_related("especialidades")
                    .order_by("nombre"),
                    many=True,
                ).data,
                "supplies": list(Supply.objects.order_by("nombre").values("id", "nombre")),
            }
        )
