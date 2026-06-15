from datetime import UTC, date, datetime, time, timedelta

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from plannings.models import Planning
from plannings.scheduler_payload import build_scheduler_payload
from plannings.serializers import PlanningCreateSerializer, PlanningSerializer
from surgeries.models import Intervention, MedicalStaff, OperatingRoom, Specialty, Surgery


def planning_queryset():
    return Planning.objects.all()


def request_scheduler_planning(payload: dict) -> dict:
    url = f"{settings.SCHEDULER_BASE_URL.rstrip('/')}/planning"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"No se pudo conectar con el Scheduler: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(response.text)
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"El Scheduler devolvió una respuesta inválida: {response.text}") from exc


def request_scheduler_status(scheduler_uuid: str) -> dict | None:
    url = f"{settings.SCHEDULER_BASE_URL.rstrip('/')}/planning/{scheduler_uuid}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"No se pudo conectar con el Scheduler: {exc}") from exc
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(response.text)
    return response.json()


class PlanningListCreateView(APIView):
    def post(self, request):
        serializer = PlanningCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        week_start = serializer.validated_data["week_start"].isoformat()

        pending_surgeries = list(
            Surgery.objects.filter(estado="Pendiente")
            .select_related("especialidad", "cirujano_forzado")
            .prefetch_related("intervenciones__intervencion")
            .order_by("-prioridad_clinica", "created_at")
        )
        payload = build_scheduler_payload(
            week_start=week_start,
            pending_surgeries=pending_surgeries,
            operating_rooms=list(OperatingRoom.objects.filter(disponible=True).order_by("nombre")),
            medical_staff=list(
                MedicalStaff.objects.filter(estado=True)
                .prefetch_related("especialidades", "disponibilidades")
                .order_by("nombre")
            ),
            specialties=list(Specialty.objects.filter(estado=True).order_by("nombre")),
            interventions=list(Intervention.objects.filter(estado=True).order_by("nombre")),
        )
        try:
            scheduler_response = request_scheduler_planning(payload)
        except RuntimeError as exc:
            return Response({"detail": f"Scheduler request failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        scheduler_uuid = scheduler_response.get("uuid")
        if not scheduler_uuid:
            return Response(
                {"detail": f"Scheduler response missing uuid: {scheduler_response}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        planning = Planning.objects.create(
            scheduler_uuid=scheduler_uuid,
            status=scheduler_response.get("status", "planning"),
            input_payload=payload,
            progress_percentage=scheduler_response.get("progress_percentage", 0),
            started_at=timezone.now(),
        )
        return Response(
            {"id": planning.id, "scheduler_uuid": planning.scheduler_uuid, "status": planning.status},
            status=status.HTTP_202_ACCEPTED,
        )


class PlanningDetailView(APIView):
    def get_object(self, scheduler_uuid: str) -> Planning | None:
        return planning_queryset().filter(scheduler_uuid=scheduler_uuid).first()

    def get(self, request, scheduler_uuid: str):
        planning = self.get_object(scheduler_uuid)
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        if planning.status == "planning":
            try:
                scheduler_status = request_scheduler_status(scheduler_uuid)
            except RuntimeError as exc:
                return Response({"detail": f"Scheduler status request failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
            if scheduler_status is not None:
                planning.progress_percentage = scheduler_status.get("progress_percentage", planning.progress_percentage)
                planning.save(update_fields=["progress_percentage", "updated_at"])
        return Response(PlanningSerializer(planning).data)

    def delete(self, request, scheduler_uuid: str):
        planning = self.get_object(scheduler_uuid)
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        if planning.status == "planning":
            return Response({"detail": "No se puede eliminar una planificación en curso"}, status=status.HTTP_409_CONFLICT)
        planning.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanningApproveView(APIView):
    def post(self, request, scheduler_uuid: str):
        if getattr(request.user, "rol", None) != "Cirujano":
            return Response({"detail": "Sólo un usuario Cirujano puede aprobar la planificación"}, status=status.HTTP_403_FORBIDDEN)
        planning = planning_queryset().filter(scheduler_uuid=scheduler_uuid).first()
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        if planning.status == "approved":
            return Response({"detail": "La planificación ya fue aprobada"}, status=status.HTTP_409_CONFLICT)
        if planning.status != "completed":
            return Response({"detail": "Sólo se puede aprobar una planificación completada"}, status=status.HTTP_409_CONFLICT)
        if not planning.output_payload:
            return Response({"detail": "La planificación no tiene resultado para aprobar"}, status=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            apply_planning_to_surgeries(planning)
            planning.status = "approved"
            planning.approved_at = timezone.now()
            planning.approved_by = request.user.email
            planning.save()
        return Response(PlanningSerializer(planning).data)


@method_decorator(csrf_exempt, name="dispatch")
class SchedulerCallbackView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if request.headers.get("X-Scheduler-Token") != settings.SCHEDULER_CALLBACK_TOKEN:
            return Response({"detail": "Invalid scheduler token"}, status=status.HTTP_403_FORBIDDEN)
        scheduler_uuid = request.data.get("uuid")
        planning = planning_queryset().filter(scheduler_uuid=scheduler_uuid).first()
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)

        planning.status = request.data.get("status", planning.status)
        planning.output_payload = request.data.get("output_payload")
        planning.error_message = request.data.get("error_message")
        planning.duration_seconds = request.data.get("duration_seconds")
        if planning.status == "completed":
            planning.progress_percentage = 100
        planning.finished_at = timezone.now()
        planning.save()
        return Response(PlanningSerializer(planning).data)


def apply_planning_to_surgeries(planning: Planning) -> None:
    surgery_map = planning.input_payload.get("id_maps", {}).get("surgeries", {})
    room_map = planning.input_payload.get("id_maps", {}).get("operating_rooms", {})
    reverse_surgery_map = {int(value): key for key, value in surgery_map.items()}
    room_by_scheduler_name = {
        room["name"]: source_id
        for source_id, scheduler_id in room_map.items()
        for room in planning.input_payload.get("operating_rooms", [])
        if room.get("id") == scheduler_id
    }
    week_start = date.fromisoformat(planning.input_payload["week_start"])

    for day_index, day in enumerate(planning.output_payload.get("dias", [])):
        current_date = week_start + timedelta(days=day_index)
        for block in day.get("bloques", []):
            room_id = room_by_scheduler_name.get(block.get("quirofano"))
            for item in block.get("cronograma", []):
                surgery_id = reverse_surgery_map.get(int(item["paciente_id"]))
                if surgery_id is None:
                    continue
                Surgery.objects.filter(id=surgery_id).update(
                    estado="Programada",
                    sala_id=room_id,
                    inicio=combine_date_and_hour(current_date, item["hora_inicio"]),
                    fin=combine_date_and_hour(current_date, item["hora_fin"]),
                )


def combine_date_and_hour(day: date, hour: str) -> datetime:
    parsed = time.fromisoformat(hour)
    return datetime.combine(day, parsed, tzinfo=UTC)
