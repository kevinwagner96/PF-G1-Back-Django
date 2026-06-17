from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CREATE_PLANNING_PERMISSION, has_explicit_permission
from plannings.models import Planning
from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    OperatingRoom,
    Specialty,
    Surgery,
)
from surgeries.serializers import (
    AnesthesiaTypeCatalogSerializer,
    InterventionCatalogSerializer,
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
        "paciente", "especialidad", "sala", "tipo_anestesia", "cirujano_forzado"
    ).prefetch_related("intervenciones__intervencion", "insumos__insumo")


def has_active_planning() -> bool:
    return Planning.objects.filter(status__in=Planning.ACTIVE_STATUSES).exists()


def require_surgery_management_permission(request):
    return has_explicit_permission(request.user, CREATE_PLANNING_PERMISSION)


class SurgeryListView(APIView):
    def get(self, request):
        return Response(SurgeryListSerializer(surgery_queryset(), many=True).data)

    @transaction.atomic
    def post(self, request):
        if not require_surgery_management_permission(request):
            return Response({"detail": "No tiene permiso para gestionar cirugías"}, status=status.HTTP_403_FORBIDDEN)
        if has_active_planning():
            return Response(
                {"detail": "No se pueden modificar cirugías mientras hay una planificación activa"},
                status=status.HTTP_409_CONFLICT,
            )

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
        if has_active_planning():
            return Response(
                {"detail": "No se pueden modificar cirugías mientras hay una planificación activa"},
                status=status.HTTP_409_CONFLICT,
            )

        surgery = Surgery.objects.filter(id=surgery_id).first()
        if surgery is None:
            return Response({"detail": "Surgery not found"}, status=status.HTTP_404_NOT_FOUND)
        if surgery.estado != "Pendiente":
            return Response({"detail": "Solo se pueden editar cirugías pendientes"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SurgeryWriteSerializer(instance=surgery, data=request.data)
        serializer.is_valid(raise_exception=True)
        surgery = serializer.save()
        return Response(SurgeryListSerializer(surgery_queryset().get(id=surgery.id)).data)


class SurgeryCancelView(APIView):
    @transaction.atomic
    def post(self, request, surgery_id: str):
        if not require_surgery_management_permission(request):
            return Response({"detail": "No tiene permiso para gestionar cirugías"}, status=status.HTTP_403_FORBIDDEN)
        if has_active_planning():
            return Response(
                {"detail": "No se pueden modificar cirugías mientras hay una planificación activa"},
                status=status.HTTP_409_CONFLICT,
            )

        surgery = Surgery.objects.filter(id=surgery_id).first()
        if surgery is None:
            return Response({"detail": "Surgery not found"}, status=status.HTTP_404_NOT_FOUND)
        if surgery.estado not in {"Pendiente", "Programada"}:
            return Response({"detail": "Solo se pueden cancelar cirugías pendientes o programadas"}, status=status.HTTP_400_BAD_REQUEST)

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
                "surgeons": MedicalStaffCatalogSerializer(MedicalStaff.objects.filter(estado=True, rol__iexact="cirujano").order_by("nombre"), many=True).data,
            }
        )
