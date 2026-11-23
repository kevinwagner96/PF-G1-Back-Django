from datetime import UTC, datetime, time, timedelta
from itertools import combinations

from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from accounts.permissions import (
    APPROVE_PLANNING_PERMISSION,
    CREATE_PLANNING_PERMISSION,
    has_explicit_permission,
)
from plannings.models import (
    AppliedSurgery,
    Planning,
    PlanningAuditEvent,
    PlanningEditLock,
    PlanningVersion,
    PlanningVote,
    SpecialtyChief,
)
from plannings.scheduler_payload import (
    DAY_START_MINUTE,
    ROOM_TYPE_RANK,
    SCHEDULER_DEFAULT_CONFIG,
    build_scheduler_availability,
    required_room_type_for_intervention,
)
from surgeries.models import MedicalStaff, OperatingRoom, Specialty, Surgery

EDIT_SPECIALTY_PERMISSION = "plannings.can_edit_specialty_planning"


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "La planificación cambió. Volvé a cargarla."


def audit(planning, action, summary, *, actor=None, surgery=None, metadata=None, source="user"):
    return PlanningAuditEvent.objects.create(
        planning=planning, action=action, summary=summary, actor=actor, surgery=surgery,
        actor_email=actor.email if actor else None, metadata=metadata or {}, source=source,
    )


def is_admin(user):
    return has_explicit_permission(user, CREATE_PLANNING_PERMISSION)


def staff_specialties(user):
    if not user.personal_id or not user.is_active or user.bloqueado:
        return set()
    staff = MedicalStaff.objects.filter(pk=user.personal_id, estado=True, rol__iexact="cirujano").first()
    return set(staff.especialidades.filter(estado=True).values_list("id", flat=True)) if staff else set()


def chiefs(*, lock=False):
    query = SpecialtyChief.objects.filter(specialty__estado=True).select_related("user", "specialty")
    if lock:
        # Serialize consensus with the creation and reassignment of jefaturas.
        list(Specialty.objects.select_for_update(no_key=True).filter(estado=True).order_by("pk").values_list("pk", flat=True))
        query = query.select_for_update(of=("self",))
    return list(query.order_by("specialty_id"))


def eligible_chief(chief):
    return (
        chief.specialty_id in staff_specialties(chief.user)
        and has_explicit_permission(chief.user, APPROVE_PLANNING_PERMISSION)
    )


def can_edit(user, *, urgent=False, lock_roster=False):
    if is_admin(user):
        return True
    if urgent:
        if lock_roster:
            return any(chief.user_id == user.pk and eligible_chief(chief) for chief in chiefs(lock=True))
        return has_explicit_permission(user, APPROVE_PLANNING_PERMISSION) and (
            SpecialtyChief.objects.filter(user=user, specialty_id__in=staff_specialties(user)).exists()
        )
    return has_explicit_permission(user, EDIT_SPECIALTY_PERMISSION) and bool(staff_specialties(user))


def session_digest(request):
    return salted_hmac("planning-edit-session", request.session.session_key or "", algorithm="sha256").hexdigest()


def owns_lock(lock, request):
    return lock.actor_id == request.user.pk and lock.session_digest == session_digest(request)


def release_lock(lock, actor, *, reason, recovered=False):
    action = PlanningAuditEvent.Action.LOCK_RECOVERED if recovered else PlanningAuditEvent.Action.LOCK_RELEASED
    audit(lock.planning, action, action.label, actor=actor, metadata={
        "version": lock.version.number, "reason": reason, "editor": lock.actor.nombre, "urgent": lock.urgent,
    })
    lock.delete()


def release_session_locks(request):
    ids = list(PlanningEditLock.objects.filter(
        actor=request.user, session_digest=session_digest(request),
    ).values_list("planning_id", flat=True))
    # Keep the same outer row lock order as edits and votes.
    for planning in Planning.objects.select_for_update().filter(pk__in=ids).order_by("pk"):
        lock = PlanningEditLock.objects.filter(planning=planning).first()
        if lock and owns_lock(lock, request):
            release_lock(lock, request.user, reason="Cierre de sesión")


def assignment(surgery, room_id, start):
    end = start + timedelta(minutes=surgery.duracion_estimada_minutos)
    return {
        "surgery_id": surgery.pk, "room_id": room_id, "surgeon_id": surgery.cirujano_forzado_id,
        "starts_at": start.isoformat(), "ends_at": end.isoformat(),
    }


def effective_agenda(planning):
    return {
        surgery.pk: {
            "surgery_id": surgery.pk, "room_id": surgery.sala_id,
            "surgeon_id": surgery.cirujano_forzado_id,
            "starts_at": surgery.inicio.isoformat(), "ends_at": surgery.fin.isoformat(),
        }
        for surgery in Surgery.objects.filter(
            appliedsurgery__planning=planning, inicio__isnull=False, fin__isnull=False,
        ).exclude(estado__in=["Pendiente", "Cancelada"])
    }


def editable_agenda(planning):
    if planning.status == Planning.STATUS_APPROVED:
        return effective_agenda(planning)
    return planning.current_version.assignments


def agenda_diff(before, after):
    return [
        {"surgery_id": key, "before": before.get(key), "after": after.get(key)}
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != after.get(key)
    ]


def load_surgeries(ids):
    rows = Surgery.objects.select_for_update(of=("self",)).filter(pk__in=ids).order_by("pk").select_related(
        "especialidad", "cirujano_forzado",
    ).prefetch_related(
        "intervenciones__intervencion__especialidad",
        "cirujano_forzado__especialidades",
        "cirujano_forzado__disponibilidades",
    )
    return {surgery.pk: surgery for surgery in rows}


def build_edited_agenda(planning, before, operations, *, actor, urgent, emergency=None):
    result = dict(before)
    seen = set()
    ids = {
        identifier
        for operation in operations
        for identifier in (operation["surgery_id"], operation.get("other_surgery_id"))
        if identifier
    }
    surgeries = load_surgeries(before.keys() | ids)
    if not ids <= surgeries.keys():
        raise ValidationError({"detail": "Una de las cirugías seleccionadas no existe."})
    allowed = staff_specialties(actor) if not (urgent or is_admin(actor)) else None

    for operation in operations:
        kind, key = operation["kind"], operation["surgery_id"]
        other = operation.get("other_surgery_id")
        selected = {key, other} if other else {key}
        if seen & selected or key == other:
            raise ValidationError({"detail": "Cada cirugía puede participar en una sola operación."})
        seen.update(selected)
        if allowed is not None and any(surgeries[item].especialidad_id not in allowed for item in selected):
            raise PermissionDenied("Una de las cirugías pertenece a otra especialidad.")
        if kind == "assign":
            if key in before:
                raise ValidationError({"detail": "La cirugía ya está en la propuesta."})
        elif key not in before:
            raise ValidationError({"detail": "La cirugía seleccionada no figura en la propuesta."})
        if kind in {"assign", "move"}:
            result[key] = assignment(surgeries[key], operation["room_id"], operation["starts_at"])
        elif kind == "remove":
            del result[key]
        elif kind == "replace":
            if other in before:
                raise ValidationError({"detail": "La cirugía sustituta debe estar fuera de la propuesta."})
            result[other] = assignment(
                surgeries[other], before[key]["room_id"], datetime.fromisoformat(before[key]["starts_at"]),
            )
            del result[key]
        elif kind == "swap":
            if other not in before:
                raise ValidationError({"detail": "Ambas cirugías deben estar en la propuesta."})
            for source, target in ((key, other), (other, key)):
                result[source] = assignment(
                    surgeries[source], before[target]["room_id"],
                    datetime.fromisoformat(before[target]["starts_at"]),
                )
    if emergency:
        surgery, room, start = emergency
        result[surgery.pk] = assignment(surgery, room, start)
    return result


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1] and (a[2] == b[2] or a[3] == b[3])


def interval(item):
    return (
        datetime.fromisoformat(item["starts_at"]), datetime.fromisoformat(item["ends_at"]),
        item["room_id"], item["surgeon_id"],
    )


def validate_agenda(planning, before, after):
    changed = {change["surgery_id"] for change in agenda_diff(before, after)}
    surgeries = load_surgeries(before.keys() | after.keys())
    owned = set(AppliedSurgery.objects.filter(planning=planning).values_list("surgery_id", flat=True))
    rooms = OperatingRoom.objects.in_bulk(item["room_id"] for item in after.values())
    starts = datetime.combine(planning.week_start, time.min, tzinfo=UTC)
    cutoff = starts + timedelta(days=7)
    external = Surgery.objects.filter(
        inicio__lt=cutoff, fin__gt=starts,
    ).exclude(estado__in=["Cancelada", "Pendiente"]).exclude(pk__in=owned).values_list(
        "inicio", "fin", "sala_id", "cirujano_forzado_id",
    )
    window_start = DAY_START_MINUTE
    window_end = window_start + SCHEDULER_DEFAULT_CONFIG["block_duration_min"]

    def invalid(key, message):
        raise ValidationError({"detail": f"Cirugía {key}: {message}."})

    for key in changed:
        if key not in after and key not in owned:
            continue  # Removing a proposal does not alter a surgery already booked elsewhere.
        surgery = surgeries.get(key)
        if not surgery or surgery.estado not in {"Pendiente", "Programada"}:
            invalid(key, "el estado de la cirugía no permite cambiar su asignación")
        if surgery.estado == "Programada" and key not in owned:
            invalid(key, "ya está programada en otra agenda")
        if key not in after:
            continue
        item = after[key]
        start, end, room_id, surgeon_id = interval(item)
        start_min, end_min = start.hour * 60 + start.minute, end.hour * 60 + end.minute
        day = (start.date() - planning.week_start).days
        if not (
            0 <= day < SCHEDULER_DEFAULT_CONFIG["n_days"] and start.date() == end.date()
            and not (start.second or start.microsecond or end.second or end.microsecond)
            and window_start <= start_min < end_min <= window_end
            and end - start == timedelta(minutes=surgery.duracion_estimada_minutos)
        ):
            invalid(key, "el horario y la duración deben caber en la jornada de la semana seleccionada")
        room = rooms.get(room_id)
        days = build_scheduler_availability(room.disponibilidad) if room else []
        if not room or not room.disponible or day >= len(days) or not days[day][0]:
            invalid(key, "el quirófano no está disponible ese día")
        interventions = [link.intervencion for link in surgery.intervenciones.all()]
        if not surgery.especialidad.estado or not interventions or any(
            not procedure.estado or procedure.especialidad_id != surgery.especialidad_id
            for procedure in interventions
        ):
            invalid(key, "la especialidad o las intervenciones no están habilitadas")
        if any(
            ROOM_TYPE_RANK.get(room.tipo_quirofano, -1)
            < ROOM_TYPE_RANK[required_room_type_for_intervention(procedure)]
            for procedure in interventions
        ):
            invalid(key, "el quirófano es incompatible con la intervención")
        surgeon = surgery.cirujano_forzado
        if not surgeon or not surgeon.estado or surgeon.rol.lower() != "cirujano" or surgeon.pk != surgeon_id or not any(
            specialty.pk == surgery.especialidad_id and specialty.estado for specialty in surgeon.especialidades.all()
        ):
            invalid(key, "el cirujano asignado no está habilitado para la especialidad")
        if not any(
            entry.dia == day and entry.inicio_minutos <= start_min and end_min <= entry.fin_minutos
            for entry in surgeon.disponibilidades.all()
        ):
            invalid(key, "el cirujano no está disponible en ese horario")

    intervals = {key: interval(item) for key, item in after.items()}
    for left, right in combinations(intervals, 2):
        if (left in changed or right in changed) and overlaps(intervals[left], intervals[right]):
            invalid(left, f"hay un solapamiento de quirófano o cirujano con {right}")
    for key in changed & after.keys():
        if any(overlaps(intervals[key], booked) for booked in external):
            invalid(key, "hay un solapamiento con una cirugía de la agenda efectiva")


def save_version(planning, before, after, *, actor, origin, reason, emergency=None, operations=None):
    version = PlanningVersion.objects.create(
        planning=planning, number=planning.current_version.number + 1, origin=origin,
        assignments=after, changes=agenda_diff(before, after), reason=reason,
        actor_name=actor.nombre, urgent_surgery=emergency,
    )
    planning.current_version = version
    planning.status = Planning.STATUS_PENDING_APPROVAL
    planning.save(update_fields=["current_version", "status", "updated_at"])
    audit(planning, PlanningAuditEvent.Action.VERSION_SAVED, "Versión guardada", actor=actor, metadata={
        "version": version.number, "origin": origin, "reason": reason, "changes": version.changes,
        "operations": operations or [],
    })
    return version


def apply_version(planning, version, *, actor):
    before = effective_agenda(planning)
    after = version.assignments
    validate_agenda(planning, before, after)
    for change in agenda_diff(before, after):
        key = change["surgery_id"]
        item = change["after"]
        if item:
            start, end, room_id, _ = interval(item)
            AppliedSurgery.objects.get_or_create(planning=planning, surgery_id=key)
            fields = {"estado": "Programada", "inicio": start, "fin": end, "sala_id": room_id}
        else:
            AppliedSurgery.objects.filter(planning=planning, surgery_id=key).delete()
            fields = {"estado": "Pendiente", "inicio": None, "fin": None, "sala_id": None}
        Surgery.objects.filter(pk=key).update(**fields, updated_at=timezone.now())
        audit(
            planning, PlanningAuditEvent.Action.SURGERY_SCHEDULED_FROM_PLANNING,
            "Asignación aplicada" if item else "Cirugía retirada", actor=actor, surgery=Surgery(pk=key),
            metadata={**change, "version": version.number, "origin": version.origin, "reason": version.reason},
        )
    version.applied_at = timezone.now()
    version.save(update_fields=["applied_at"])
    planning.applied_version = version
    planning.status = Planning.STATUS_APPROVED
    planning.approved_at = version.applied_at
    planning.approved_by = actor.email if version.origin != PlanningVersion.Origin.URGENT else None
    planning.save(update_fields=["applied_version", "status", "approved_at", "approved_by", "updated_at"])
    action = (
        PlanningAuditEvent.Action.URGENCY_APPLIED if version.origin == PlanningVersion.Origin.URGENT
        else PlanningAuditEvent.Action.PLANNING_APPROVED
    )
    audit(planning, action, action.label, actor=actor, metadata={
        "version": version.number, "reason": version.reason, "urgent_surgery_id": version.urgent_surgery_id,
    })


def register_votes(planning, version, actor, *, required, roster=None):
    if roster is None:
        roster = chiefs(lock=True)
    eligible = [chief for chief in roster if eligible_chief(chief)]
    actor_chiefs = [chief for chief in eligible if chief.user_id == actor.pk]
    if required and not actor_chiefs:
        raise PermissionDenied("Solo pueden votar los jefes de cirugía vigentes.")
    for chief in actor_chiefs:
        _, created = PlanningVote.objects.get_or_create(
            version=version, designation=chief.designation, defaults={
                "specialty_id": chief.specialty_id, "specialty_name": chief.specialty.nombre,
                "actor_id": actor.pk, "actor_name": actor.nombre,
            },
        )
        if created:
            audit(planning, PlanningAuditEvent.Action.VOTE_RECORDED, "Voto registrado", actor=actor, metadata={
                "version": version.number, "specialty_id": chief.specialty_id,
            })
    voted = set(version.votes.values_list("designation", flat=True))
    if roster and len(eligible) == len(roster) and {chief.designation for chief in roster} <= voted:
        apply_version(planning, version, actor=actor)
