from datetime import UTC, date, datetime, time, timedelta

from django.db import migrations


def legacy_assignments(planning, week):
    payload = planning.input_payload or {}
    result = planning.output_payload or {}
    if not isinstance(result, dict) or not isinstance(result.get("dias"), list):
        return {}
    maps = payload.get("id_maps", {})
    surgeries = {str(value): key for key, value in maps.get("surgeries", {}).items()}
    rooms = {item.get("id"): item.get("name") for item in payload.get("operating_rooms", [])}
    room_ids = {rooms.get(value): key for key, value in maps.get("operating_rooms", {}).items()}
    staff = {value: key for key, value in maps.get("medical_staff", {}).items()}
    surgeons = {str(item.get("id")): staff.get(item.get("forced_surgeon_id"))
                for item in payload.get("pending_surgeries", [])}
    assignments = {}
    for index, day in enumerate(result.get("dias", [])):
        current = week + timedelta(days=index)
        for block in day.get("bloques", []):
            room_id = room_ids.get(block.get("quirofano"))
            for item in block.get("cronograma", []):
                code = str(item.get("paciente_id"))
                surgery_id = surgeries.get(code)
                if not (room_id and surgery_id):
                    continue
                try:
                    start = datetime.combine(current, time.fromisoformat(item["hora_inicio"]), tzinfo=UTC)
                    end = datetime.combine(current, time.fromisoformat(item["hora_fin"]), tzinfo=UTC)
                except (KeyError, TypeError, ValueError):
                    continue
                assignments[surgery_id] = {
                    "surgery_id": surgery_id, "room_id": room_id, "surgeon_id": surgeons.get(code),
                    "starts_at": start.isoformat(), "ends_at": end.isoformat(),
                }
    return assignments


def migrate_agendas(apps, schema_editor):
    planning_model = apps.get_model("plannings", "Planning")
    version_model = apps.get_model("plannings", "PlanningVersion")
    applied_model = apps.get_model("plannings", "AppliedSurgery")
    audit_model = apps.get_model("plannings", "PlanningAuditEvent")
    surgery_model = apps.get_model("surgeries", "Surgery")
    db = schema_editor.connection.alias
    by_week = {}
    for planning in planning_model.objects.using(db).order_by("-created_at", "-pk").iterator():
        try:
            anchor = date.fromisoformat(planning.input_payload["week_start"])
        except (KeyError, TypeError, ValueError):
            continue
        week = anchor - timedelta(days=anchor.weekday())
        planning.week_start = week
        planning.save(using=db, update_fields=["week_start"])
        if planning.status in {"approved", "pending_approval"}:
            by_week.setdefault(week, []).append((planning, anchor))

    for week, rows in by_week.items():
        chosen = max(
            (row for row, _ in rows if row.status == "approved"),
            key=lambda row: (row.approved_at or row.created_at, row.created_at, row.pk),
            default=rows[0][0],
        )
        historical_assignments = {row.pk: legacy_assignments(row, anchor) for row, anchor in rows}
        for planning, _ in rows:
            assignments = historical_assignments[planning.pk]
            if planning.status == "pending_approval":
                for surgery in surgery_model.objects.using(db).filter(pk__in=assignments):
                    assignments[surgery.pk]["surgeon_id"] = surgery.cirujano_forzado_id
            version = version_model.objects.using(db).create(
                planning_id=planning.pk, number=1, origin="historical", assignments=assignments,
                actor_name=planning.approved_by or "",
                applied_at=(planning.approved_at or planning.finished_at or planning.created_at)
                if planning.status == "approved" else None,
            )
            planning.current_version_id = version.pk
            planning.operational = planning.pk == chosen.pk
            if planning.status == "approved":
                planning.applied_version_id = version.pk
            planning.save(using=db, update_fields=["current_version", "applied_version", "operational"])

        if chosen.status != "approved":
            continue
        # Older approvals could leave effective appointments when a second proposal was applied.
        approved_ids = [row.pk for row, _ in rows if row.status == "approved"]
        booked_ids = {
            key for row_id in approved_ids for key in historical_assignments[row_id]
        }
        booked_ids.update(audit_model.objects.using(db).filter(
            planning_id__in=approved_ids, action="surgery_scheduled_from_planning",
            surgery_id__isnull=False,
        ).values_list("surgery_id", flat=True))
        effective_ids = surgery_model.objects.using(db).filter(
            pk__in=booked_ids, inicio__date__gte=week,
            inicio__date__lt=week + timedelta(days=7), fin__isnull=False,
            sala_id__isnull=False,
        ).exclude(estado__in=["Pendiente", "Cancelada"]).values_list("pk", flat=True)
        for key in effective_ids:
            applied_model.objects.using(db).get_or_create(surgery_id=key, defaults={"planning_id": chosen.pk})


class Migration(migrations.Migration):
    dependencies = [
        ("plannings", "0005_planningvote_specialtychief_alter_planning_options_and_more"),
    ]
    operations = [migrations.RunPython(migrate_agendas, migrations.RunPython.noop)]
