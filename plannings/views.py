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

from accounts.permissions import (
    APPROVE_PLANNING_PERMISSION,
    CREATE_PLANNING_PERMISSION,
    has_explicit_permission,
)
from plannings.models import Planning, PlanningAuditEvent
from plannings.scheduler_payload import build_scheduler_payload
from plannings.serializers import (
    PlanningCreateSerializer,
    PlanningRejectSerializer,
    PlanningSerializer,
)
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


def get_audit_actor(user):
    if getattr(user, "is_authenticated", False):
        return user
    return None


def create_planning_audit_event(
    *,
    action: str,
    source: str,
    summary: str,
    planning: Planning | None = None,
    surgery: Surgery | None = None,
    actor=None,
    metadata: dict | None = None,
) -> PlanningAuditEvent:
    audit_actor = get_audit_actor(actor)
    return PlanningAuditEvent.objects.create(
        action=action,
        source=source,
        planning=planning,
        surgery=surgery,
        actor=audit_actor,
        actor_email=getattr(audit_actor, "email", None),
        summary=summary,
        metadata=metadata or {},
    )


class PlanningListCreateView(APIView):
    def post(self, request):
        if not has_explicit_permission(request.user, CREATE_PLANNING_PERMISSION):
            return Response({"detail": "No tiene permiso para generar planificaciones"}, status=status.HTTP_403_FORBIDDEN)

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
        create_planning_audit_event(
            action=PlanningAuditEvent.Action.PLANNING_REQUESTED,
            source=PlanningAuditEvent.Source.USER,
            actor=request.user,
            summary=f"Solicitud de planificación para la semana {week_start}",
            metadata={
                "week_start": week_start,
                "pending_surgeries_count": len(pending_surgeries),
                "operating_rooms_count": len(payload.get("operating_rooms", [])),
                "medical_staff_count": len(payload.get("medical_staff", [])),
            },
        )
        try:
            scheduler_response = request_scheduler_planning(payload)
        except RuntimeError as exc:
            create_planning_audit_event(
                action=PlanningAuditEvent.Action.PLANNING_REQUEST_FAILED,
                source=PlanningAuditEvent.Source.SYSTEM,
                actor=request.user,
                summary="Falló la solicitud de planificación al Scheduler",
                metadata={
                    "week_start": week_start,
                    "error": str(exc),
                    "pending_surgeries_count": len(pending_surgeries),
                },
            )
            return Response({"detail": f"Scheduler request failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        scheduler_uuid = scheduler_response.get("uuid")
        if not scheduler_uuid:
            return Response(
                {"detail": f"Scheduler response missing uuid: {scheduler_response}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        planning = Planning.objects.create(
            scheduler_uuid=scheduler_uuid,
            status=scheduler_response.get("status", Planning.STATUS_PLANNING),
            input_payload=payload,
            progress_percentage=scheduler_response.get("progress_percentage", 0),
            started_at=timezone.now(),
        )
        create_planning_audit_event(
            action=PlanningAuditEvent.Action.PLANNING_CREATED,
            source=PlanningAuditEvent.Source.USER,
            planning=planning,
            actor=request.user,
            summary=f"Planificación creada con Scheduler UUID {planning.scheduler_uuid}",
            metadata={
                "scheduler_uuid": planning.scheduler_uuid,
                "status": planning.status,
                "week_start": week_start,
                "progress_percentage": planning.progress_percentage,
                "pending_surgeries_count": len(pending_surgeries),
            },
        )
        return Response(
            {"id": planning.id, "scheduler_uuid": planning.scheduler_uuid, "status": planning.status},
            status=status.HTTP_202_ACCEPTED,
        )


class ActivePlanningView(APIView):
    def get(self, request):
        planning = planning_queryset().filter(status__in=Planning.ACTIVE_STATUSES).first()
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(PlanningSerializer(planning).data)


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
        if not has_explicit_permission(request.user, CREATE_PLANNING_PERMISSION):
            return Response({"detail": "No tiene permiso para eliminar planificaciones"}, status=status.HTTP_403_FORBIDDEN)
        planning = self.get_object(scheduler_uuid)
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        if planning.status in Planning.ACTIVE_STATUSES:
            return Response({"detail": "No se puede eliminar una planificación en curso"}, status=status.HTTP_409_CONFLICT)
        create_planning_audit_event(
            action=PlanningAuditEvent.Action.PLANNING_DELETED,
            source=PlanningAuditEvent.Source.USER,
            planning=planning,
            actor=request.user,
            summary=f"Planificación {planning.scheduler_uuid} eliminada",
            metadata={
                "scheduler_uuid": planning.scheduler_uuid,
                "status": planning.status,
            },
        )
        planning.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanningApproveView(APIView):
    def post(self, request, scheduler_uuid: str):
        if not has_explicit_permission(request.user, APPROVE_PLANNING_PERMISSION):
            return Response({"detail": "No tiene permiso para aprobar planificaciones"}, status=status.HTTP_403_FORBIDDEN)
        planning = planning_queryset().filter(scheduler_uuid=scheduler_uuid).first()
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        if planning.status == Planning.STATUS_APPROVED:
            return Response({"detail": "La planificación ya fue aprobada"}, status=status.HTTP_409_CONFLICT)
        if planning.status == Planning.STATUS_REJECTED:
            return Response({"detail": "La planificación ya fue rechazada"}, status=status.HTTP_409_CONFLICT)
        if planning.status != Planning.STATUS_PENDING_APPROVAL:
            return Response({"detail": "Sólo se puede aprobar una planificación pendiente de aprobación"}, status=status.HTTP_409_CONFLICT)
        if not planning.output_payload:
            return Response({"detail": "La planificación no tiene resultado para aprobar"}, status=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            scheduled_count = apply_planning_to_surgeries(planning, actor=request.user)
            planning.status = Planning.STATUS_APPROVED
            planning.approved_at = timezone.now()
            planning.approved_by = request.user.email
            planning.save()
            create_planning_audit_event(
                action=PlanningAuditEvent.Action.PLANNING_APPROVED,
                source=PlanningAuditEvent.Source.USER,
                planning=planning,
                actor=request.user,
                summary=f"Planificación {planning.scheduler_uuid} aprobada",
                metadata={
                    "scheduler_uuid": planning.scheduler_uuid,
                    "approved_by": planning.approved_by,
                    "scheduled_surgeries_count": scheduled_count,
                },
            )
        return Response(PlanningSerializer(planning).data)


class PlanningRejectView(APIView):
    def post(self, request, scheduler_uuid: str):
        if not has_explicit_permission(request.user, APPROVE_PLANNING_PERMISSION):
            return Response({"detail": "No tiene permiso para rechazar planificaciones"}, status=status.HTTP_403_FORBIDDEN)

        serializer = PlanningRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]

        planning = planning_queryset().filter(scheduler_uuid=scheduler_uuid).first()
        if planning is None:
            return Response({"detail": "Planning not found"}, status=status.HTTP_404_NOT_FOUND)
        if planning.status == Planning.STATUS_APPROVED:
            return Response({"detail": "La planificación ya fue aprobada"}, status=status.HTTP_409_CONFLICT)
        if planning.status == Planning.STATUS_REJECTED:
            return Response({"detail": "La planificación ya fue rechazada"}, status=status.HTTP_409_CONFLICT)
        if planning.status != Planning.STATUS_PENDING_APPROVAL:
            return Response({"detail": "Sólo se puede rechazar una planificación pendiente de aprobación"}, status=status.HTTP_409_CONFLICT)

        previous_status = planning.status
        planning.status = Planning.STATUS_REJECTED
        planning.rejected_at = timezone.now()
        planning.rejected_by = request.user.email
        planning.rejection_reason = reason
        planning.save()
        create_planning_audit_event(
            action=PlanningAuditEvent.Action.PLANNING_REJECTED,
            source=PlanningAuditEvent.Source.USER,
            planning=planning,
            actor=request.user,
            summary=f"Planificación {planning.scheduler_uuid} rechazada",
            metadata={
                "scheduler_uuid": planning.scheduler_uuid,
                "previous_status": previous_status,
                "new_status": planning.status,
                "rejected_by": planning.rejected_by,
                "reason": reason,
            },
        )
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

        scheduler_status = request.data.get("status", planning.status)
        planning.status = (
            Planning.STATUS_PENDING_APPROVAL
            if scheduler_status == "completed"
            else scheduler_status
        )
        planning.output_payload = request.data.get("output_payload")
        planning.error_message = request.data.get("error_message")
        planning.duration_seconds = request.data.get("duration_seconds")
        if scheduler_status == "completed":
            planning.progress_percentage = 100
        planning.finished_at = timezone.now()
        planning.save()
        callback_action = (
            PlanningAuditEvent.Action.PLANNING_PENDING_APPROVAL
            if planning.status == Planning.STATUS_PENDING_APPROVAL
            else PlanningAuditEvent.Action.SCHEDULER_CALLBACK_FAILED
        )
        create_planning_audit_event(
            action=callback_action,
            source=PlanningAuditEvent.Source.SCHEDULER,
            planning=planning,
            summary=f"Callback del Scheduler recibido con estado {scheduler_status}",
            metadata={
                "scheduler_uuid": planning.scheduler_uuid,
                "scheduler_status": scheduler_status,
                "status": planning.status,
                "duration_seconds": planning.duration_seconds,
                "has_output_payload": planning.output_payload is not None,
                "error_message": planning.error_message,
            },
        )
        return Response(PlanningSerializer(planning).data)


def apply_planning_to_surgeries(planning: Planning, actor=None) -> int:
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
    scheduled_count = 0

    for day_index, day in enumerate(planning.output_payload.get("dias", [])):
        current_date = week_start + timedelta(days=day_index)
        for block in day.get("bloques", []):
            room_id = room_by_scheduler_name.get(block.get("quirofano"))
            for item in block.get("cronograma", []):
                surgery_id = reverse_surgery_map.get(int(item["paciente_id"]))
                if surgery_id is None:
                    continue
                surgery = Surgery.objects.filter(id=surgery_id).first()
                if surgery is None:
                    continue

                previous_state = {
                    "estado": surgery.estado,
                    "sala_id": surgery.sala_id,
                    "inicio": surgery.inicio.isoformat() if surgery.inicio else None,
                    "fin": surgery.fin.isoformat() if surgery.fin else None,
                }
                surgery.estado = "Programada"
                surgery.sala_id = room_id
                surgery.inicio = combine_date_and_hour(current_date, item["hora_inicio"])
                surgery.fin = combine_date_and_hour(current_date, item["hora_fin"])
                surgery.save(update_fields=["estado", "sala", "inicio", "fin", "updated_at"])
                scheduled_count += 1

                create_planning_audit_event(
                    action=PlanningAuditEvent.Action.SURGERY_SCHEDULED_FROM_PLANNING,
                    source=PlanningAuditEvent.Source.USER,
                    planning=planning,
                    surgery=surgery,
                    actor=actor,
                    summary=f"Cirugía {surgery.id} programada desde planificación {planning.scheduler_uuid}",
                    metadata={
                        "scheduler_uuid": planning.scheduler_uuid,
                        "surgery_id": surgery.id,
                        "previous": previous_state,
                        "new": {
                            "estado": surgery.estado,
                            "sala_id": surgery.sala_id,
                            "inicio": surgery.inicio.isoformat() if surgery.inicio else None,
                            "fin": surgery.fin.isoformat() if surgery.fin else None,
                        },
                        "scheduler_item": {
                            "paciente_id": item.get("paciente_id"),
                            "hora_inicio": item.get("hora_inicio"),
                            "hora_fin": item.get("hora_fin"),
                            "quirofano": block.get("quirofano"),
                        },
                    },
                )
    return scheduled_count


def combine_date_and_hour(day: date, hour: str) -> datetime:
    parsed = time.fromisoformat(hour)
    return datetime.combine(day, parsed, tzinfo=UTC)
