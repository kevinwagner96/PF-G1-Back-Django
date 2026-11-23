from datetime import UTC, datetime, time, timedelta
from hmac import compare_digest

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from plannings.agenda import (
    Conflict,
    agenda_diff,
    apply_version,
    audit,
    build_edited_agenda,
    can_edit,
    chiefs,
    editable_agenda,
    is_admin,
    owns_lock,
    register_votes,
    release_lock,
    save_version,
    session_digest,
    validate_agenda,
)
from plannings.models import (
    Planning,
    PlanningAuditEvent,
    PlanningEditLock,
    PlanningVersion,
    new_uuid,
)
from plannings.preflight import build_planning_preflight
from plannings.scheduler_payload import build_scheduler_payload
from plannings.serializers import (
    AcquireSerializer,
    EditSerializer,
    PlanningAuditSerializer,
    PlanningCreateSerializer,
    PlanningSerializer,
    PlanningVersionSerializer,
    RecoverSerializer,
    ReleaseSerializer,
    VersionSerializer,
)
from surgeries.models import Intervention, MedicalStaff, OperatingRoom, Specialty, Surgery
from surgeries.serializers import EmergencySurgerySerializer

CALLBACK_GRACE_SECONDS = 5
DISPATCH_GRACE_SECONDS = 35


def request_scheduler_planning(payload):
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{settings.SCHEDULER_BASE_URL.rstrip('/')}/planning", json=payload)
        response.raise_for_status()
        return response.json()


def request_scheduler_status(scheduler_uuid):
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{settings.SCHEDULER_BASE_URL.rstrip('/')}/planning/{scheduler_uuid}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def one_planning(uuid, *, lock=False):
    queryset = Planning.objects
    if lock:
        queryset = queryset.select_for_update()
    planning = queryset.filter(scheduler_uuid=uuid).first()
    if planning is None:
        raise NotFound("No se encontró la planificación.")
    return planning


def render(request, planning):
    return PlanningSerializer(planning, context={"request": request}).data


def validate_input(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def fail_attempt(planning, message, *, action=PlanningAuditEvent.Action.SCHEDULER_CALLBACK_FAILED, output=None):
    planning.status = Planning.STATUS_FAILED
    planning.operational = False
    planning.error_message = message
    planning.finished_at = timezone.now()
    if output is not None:
        planning.output_payload = output
    planning.save()
    audit(planning, action, "Falló la generación de la propuesta", source="scheduler", metadata={"error": message})


def initial_agenda(planning, output):
    input_payload = planning.input_payload
    maps = input_payload["id_maps"]
    surgeries = {str(index): key for key, index in maps["surgeries"].items()}
    staff = {index: key for key, index in maps["medical_staff"].items()}
    surgeon_for_surgery = {
        str(item["id"]): staff[item["forced_surgeon_id"]] for item in input_payload["pending_surgeries"]
    }
    room_names = {item["id"]: item["name"] for item in input_payload["operating_rooms"]}
    rooms = {room_names[index]: key for key, index in maps["operating_rooms"].items()}
    days = output["dias"]
    if not isinstance(days, list) or len(days) != input_payload["config"]["n_days"]:
        raise ValueError("El resultado no contiene todos los días de la semana.")
    assignments = {}
    for offset, day in enumerate(days):
        day_date = planning.week_start + timedelta(days=offset)
        for block in day["bloques"]:
            room = rooms[block["quirofano"]]
            for item in block["cronograma"]:
                index = str(item["paciente_id"])
                key = surgeries[index]
                if key in assignments:
                    raise ValueError("El resultado repite una cirugía.")
                start = datetime.combine(day_date, time.fromisoformat(item["hora_inicio"]), tzinfo=UTC)
                end = datetime.combine(day_date, time.fromisoformat(item["hora_fin"]), tzinfo=UTC)
                assignments[key] = {
                    "surgery_id": key, "room_id": room, "surgeon_id": surgeon_for_surgery[index],
                    "starts_at": start.isoformat(), "ends_at": end.isoformat(),
                }
    return assignments


class PlanningListCreateView(APIView):
    def get(self, request):
        week = validate_input(PlanningCreateSerializer, request.query_params)["week_start"]
        rows = Planning.objects.filter(week_start=week)
        planning = rows.filter(operational=True).first() or rows.filter(status=Planning.STATUS_FAILED).first()
        return Response({
            "planning": render(request, planning) if planning else None,
            "attempts": list(rows.values("scheduler_uuid", "status", "operational", "created_at")),
        })

    def post(self, request):
        if not is_admin(request.user):
            raise PermissionDenied("No tiene permiso para generar planificaciones.")
        week = validate_input(PlanningCreateSerializer, request.data)["week_start"]
        if Planning.objects.filter(operational=True, week_start=week).exists():
            raise Conflict("Ya existe una generación o propuesta válida para esa semana.")
        preflight = build_planning_preflight()
        if not preflight["can_plan"]:
            return Response({
                "detail": "No se puede generar la planificación con los datos actuales.",
                "preflight": preflight,
            }, status=status.HTTP_400_BAD_REQUEST)

        job_uuid = new_uuid()
        payload = build_scheduler_payload(
            week_start=week.isoformat(),
            pending_surgeries=list(Surgery.objects.filter(estado="Pendiente").select_related(
                "especialidad", "cirujano_forzado",
            ).prefetch_related("intervenciones__intervencion").order_by("-prioridad_clinica", "created_at")),
            operating_rooms=list(OperatingRoom.objects.filter(disponible=True).order_by("nombre")),
            medical_staff=list(MedicalStaff.objects.filter(estado=True).prefetch_related(
                "especialidades", "disponibilidades",
            ).order_by("nombre")),
            specialties=list(Specialty.objects.filter(estado=True)),
            interventions=list(Intervention.objects.filter(estado=True)),
        )
        payload["job_uuid"] = job_uuid
        supplied_rooms = payload["id_maps"]["operating_rooms"]
        supplied_staff = payload["id_maps"]["medical_staff"]
        start = datetime.combine(week, time.min, tzinfo=UTC)
        payload["bookings"] = [
            {
                "day": (begin.date() - week).days,
                "start": begin.hour * 60 + begin.minute, "end": end.hour * 60 + end.minute,
                "room_id": supplied_rooms.get(room), "surgeon_id": supplied_staff.get(surgeon),
            }
            for begin, end, room, surgeon in Surgery.objects.filter(
                inicio__gte=start, inicio__lt=start + timedelta(days=7), fin__isnull=False,
            ).exclude(estado__in=["Pendiente", "Cancelada"]).values_list(
                "inicio", "fin", "sala_id", "cirujano_forzado_id",
            )
            if begin.date() == end.date() and (room in supplied_rooms or surgeon in supplied_staff)
        ]
        try:
            with transaction.atomic():
                planning = Planning.objects.create(
                    scheduler_uuid=job_uuid, operational=True, week_start=week,
                    status=Planning.STATUS_PLANNING, input_payload=payload, started_at=timezone.now(),
                )
                audit(planning, PlanningAuditEvent.Action.PLANNING_REQUESTED, "Generación solicitada", actor=request.user)
        except IntegrityError:
            if Planning.objects.filter(week_start=week, operational=True).exists():
                raise Conflict("Ya existe una generación o propuesta válida para esa semana.") from None
            raise

        try:
            result = request_scheduler_planning(payload)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError, ValueError):
            result = None
        except (httpx.TransportError, RuntimeError):
            # The Scheduler may have accepted the job before the connection was lost.
            # The registered UUID lets polling or the callback resolve that outcome.
            result = {"uuid": job_uuid}
        if not isinstance(result, dict) or result.get("uuid") != job_uuid:
            with transaction.atomic():
                planning = one_planning(job_uuid, lock=True)
                if planning.status == Planning.STATUS_PLANNING:
                    fail_attempt(
                        planning, "El Scheduler no aceptó el intento registrado.",
                        action=PlanningAuditEvent.Action.PLANNING_REQUEST_FAILED,
                    )
                    return Response({"detail": planning.error_message}, status=status.HTTP_502_BAD_GATEWAY)
        planning.refresh_from_db()
        return Response(
            {"id": planning.id, "scheduler_uuid": job_uuid, "status": planning.status},
            status=status.HTTP_202_ACCEPTED,
        )


class PlanningPreflightView(APIView):
    def get(self, request):
        if not is_admin(request.user):
            raise PermissionDenied("No tiene permiso para generar planificaciones.")
        return Response(build_planning_preflight())


class ActivePlanningView(APIView):
    def get(self, request):
        planning = Planning.objects.filter(operational=True, status__in=Planning.ACTIVE_STATUSES).first()
        if planning is None:
            raise NotFound("No hay una planificación activa.")
        return Response(render(request, planning))


class PlanningDetailView(APIView):
    def get(self, request, scheduler_uuid):
        planning = one_planning(scheduler_uuid)
        if not planning.operational or planning.status != Planning.STATUS_PLANNING:
            return Response(render(request, planning))
        try:
            remote = request_scheduler_status(scheduler_uuid)
        except (httpx.HTTPError, ValueError, RuntimeError):
            return Response(render(request, planning))
        with transaction.atomic():
            planning = one_planning(scheduler_uuid, lock=True)
            if planning.status != Planning.STATUS_PLANNING or not planning.operational:
                return Response(render(request, planning))
            now = timezone.now()
            if not remote:
                if (now - (planning.started_at or planning.created_at)).total_seconds() >= DISPATCH_GRACE_SECONDS:
                    fail_attempt(planning, "El Scheduler ya no tiene el intento registrado.")
            elif remote.get("status") == "failed":
                fail_attempt(planning, remote.get("error_message") or "El Scheduler informó un fallo.")
            elif remote.get("status") == "completed":
                if planning.progress_percentage < 100:
                    planning.progress_percentage = 100
                    planning.save(update_fields=["progress_percentage", "updated_at"])
                elif (now - planning.updated_at).total_seconds() >= CALLBACK_GRACE_SECONDS:
                    fail_attempt(planning, "El Scheduler terminó, pero no se recibió el resultado.")
        return Response(render(request, planning))


def confirm_version(planning, number):
    if not planning.operational or not planning.current_version_id or planning.current_version.number != number:
        raise Conflict()


def require_lock(planning, request, token):
    lock = PlanningEditLock.objects.filter(planning=planning).first()
    if not lock or lock.token != token or not owns_lock(lock, request):
        raise Conflict("El bloqueo de edición ya no pertenece a esta sesión.")
    return lock


class PlanningApproveView(APIView):
    @transaction.atomic
    def post(self, request, scheduler_uuid):
        data = validate_input(VersionSerializer, request.data)
        planning = one_planning(scheduler_uuid, lock=True)
        confirm_version(planning, data["version"])
        if planning.status != Planning.STATUS_PENDING_APPROVAL or PlanningEditLock.objects.filter(planning=planning).exists():
            raise Conflict("La versión no está disponible para votar.")
        register_votes(planning, planning.current_version, request.user, required=True)
        return Response(render(request, planning))


class PlanningLockView(APIView):
    @transaction.atomic
    def post(self, request, scheduler_uuid):
        data = validate_input(AcquireSerializer, request.data)
        planning = one_planning(scheduler_uuid, lock=True)
        confirm_version(planning, data["version"])
        urgent = data["urgent"]
        if urgent and planning.status != Planning.STATUS_APPROVED:
            raise Conflict("La urgencia requiere una agenda aprobada.")
        if not can_edit(request.user, urgent=urgent):
            raise PermissionDenied("No tenés permiso para editar esta planificación.")
        lock = PlanningEditLock.objects.filter(planning=planning).first()
        if lock and not (owns_lock(lock, request) and lock.urgent == urgent):
            raise Conflict("La planificación está en edición.")
        if not lock:
            lock = PlanningEditLock.objects.create(
                planning=planning, version=planning.current_version, actor=request.user,
                session_digest=session_digest(request), urgent=urgent,
            )
            audit(planning, PlanningAuditEvent.Action.LOCK_ACQUIRED, "Edición iniciada", actor=request.user, metadata={
                "version": data["version"], "urgent": urgent,
            })
        return Response({"lock_token": lock.token, "version": lock.version.number})

    @transaction.atomic
    def delete(self, request, scheduler_uuid):
        data = validate_input(ReleaseSerializer, request.data)
        planning = one_planning(scheduler_uuid, lock=True)
        lock = require_lock(planning, request, data["lock_token"])
        release_lock(lock, request.user, reason="Edición cancelada")
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanningRecoverView(APIView):
    @transaction.atomic
    def post(self, request, scheduler_uuid):
        if not is_admin(request.user):
            raise PermissionDenied("Solo un administrador puede recuperar el bloqueo.")
        data = validate_input(RecoverSerializer, request.data)
        planning = one_planning(scheduler_uuid, lock=True)
        lock = PlanningEditLock.objects.filter(planning=planning).first()
        if not lock:
            raise Conflict("No hay un bloqueo activo.")
        release_lock(lock, request.user, reason=data["reason"], recovered=True)
        return Response(render(request, planning))


class PlanningEditView(APIView):
    @transaction.atomic
    def post(self, request, scheduler_uuid):
        data = validate_input(EditSerializer, request.data)
        planning = one_planning(scheduler_uuid, lock=True)
        confirm_version(planning, data["version"])
        lock = require_lock(planning, request, data["lock_token"])
        if lock.version_id != planning.current_version_id:
            raise Conflict()
        urgent = lock.urgent
        if not can_edit(request.user, urgent=urgent, lock_roster=urgent):
            raise PermissionDenied("No tenés permiso para editar esta planificación.")
        roster = chiefs(lock=True) if not urgent else None
        before = editable_agenda(planning)
        emergency = None
        if urgent:
            if planning.status != Planning.STATUS_APPROVED:
                raise Conflict("La urgencia requiere una agenda aprobada.")
            if not data["reason"] or "emergency" not in data:
                raise ValidationError({"detail": "Completá los datos y el motivo de la urgencia."})
            emergency_data = EmergencySurgerySerializer(data=data["emergency"])
            emergency_data.is_valid(raise_exception=True)
            surgery = emergency_data.save()
            emergency = (surgery, emergency_data.validated_data["room_id"], emergency_data.validated_data["starts_at"])
        elif "emergency" in data:
            raise ValidationError({"detail": "Adquirí el bloqueo de urgencia para registrar una urgencia."})
        after = build_edited_agenda(
            planning, before, data["operations"], actor=request.user, urgent=urgent, emergency=emergency,
        )
        if before != after:
            if not data["reason"]:
                raise ValidationError({"detail": "Indicá el motivo de los cambios."})
            validate_agenda(planning, before, after)
            version = save_version(
                planning, before, after, actor=request.user, reason=data["reason"],
                origin=PlanningVersion.Origin.URGENT if urgent else PlanningVersion.Origin.ORDINARY,
                emergency=emergency[0] if emergency else None,
                operations=[{**item, "starts_at": item["starts_at"].isoformat()} if "starts_at" in item else item
                            for item in data["operations"]],
            )
            if urgent:
                apply_version(planning, version, actor=request.user)
            else:
                register_votes(planning, version, request.user, required=False, roster=roster)
        release_lock(lock, request.user, reason="Edición guardada")
        return Response(render(request, planning))


class PlanningHistoryView(APIView):
    def get(self, request, scheduler_uuid):
        planning = one_planning(scheduler_uuid)
        return Response({
            "versions": PlanningVersionSerializer(planning.versions.prefetch_related("votes"), many=True).data,
            "events": PlanningAuditSerializer(planning.audit_events.all(), many=True).data,
        })


class SchedulerCallbackView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        token = request.headers.get("X-Scheduler-Token", "")
        if not compare_digest(token.encode(), settings.SCHEDULER_CALLBACK_TOKEN.encode()):
            raise PermissionDenied("Token del Scheduler inválido.")
        planning = one_planning(request.data.get("uuid"), lock=True)
        if not planning.operational or planning.status != Planning.STATUS_PLANNING or planning.current_version_id:
            return Response({"status": planning.status})
        outcome = request.data.get("status")
        if outcome not in {"failed", "completed"}:
            raise ValidationError({"detail": "Estado del Scheduler inválido."})
        output = request.data.get("output_payload")
        if outcome == "failed":
            fail_attempt(planning, str(request.data.get("error_message") or "El Scheduler informó un fallo."), output=output)
            return Response({"status": planning.status})
        try:
            assignments = initial_agenda(planning, output)
            validate_agenda(planning, {}, assignments)
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            detail = error.detail.get("detail") if isinstance(error, ValidationError) else str(error)
            fail_attempt(planning, f"Resultado inválido del Scheduler: {detail}", output=output)
            return Response({"status": planning.status})
        planning.current_version = PlanningVersion.objects.create(
            planning=planning, number=1, origin=PlanningVersion.Origin.SCHEDULER, assignments=assignments,
            changes=agenda_diff({}, assignments),
        )
        planning.status = Planning.STATUS_PENDING_APPROVAL
        planning.output_payload = output
        planning.progress_percentage = 100
        planning.finished_at = timezone.now()
        duration = request.data.get("duration_seconds")
        planning.duration_seconds = duration if isinstance(duration, (int, float)) else None
        planning.save()
        audit(
            planning, PlanningAuditEvent.Action.PLANNING_PENDING_APPROVAL, "Propuesta inicial recibida",
            source="scheduler", metadata={"version": 1},
        )
        return Response({"status": planning.status})
