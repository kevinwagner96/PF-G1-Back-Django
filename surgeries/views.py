from rest_framework.response import Response
from rest_framework.views import APIView

from surgeries.models import MedicalStaff, OperatingRoom, Surgery
from surgeries.serializers import (
    MedicalStaffSerializer,
    OperatingRoomSerializer,
    PendingSurgerySerializer,
    SurgeryListSerializer,
)


def surgery_queryset():
    return Surgery.objects.select_related(
        "paciente", "especialidad", "sala", "tipo_anestesia"
    ).prefetch_related("intervenciones__intervencion", "insumos__insumo")


class SurgeryListView(APIView):
    def get(self, request):
        return Response(SurgeryListSerializer(surgery_queryset(), many=True).data)


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
