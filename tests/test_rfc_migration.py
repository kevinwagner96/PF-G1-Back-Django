from datetime import UTC, date, datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from demo.seed import PROC_GENERAL, ROOM_2, STAFF_2
from plannings.models import AppliedSurgery, Planning, PlanningAuditEvent, PlanningVote
from surgeries.models import Surgery, SurgerySupply


@pytest.mark.django_db(transaction=True)
def test_rfc_migration_preserves_duplicate_weeks_and_effective_surgery():
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    prior = [
        ("demo", "0004_admin_can_approve_planning"),
        ("plannings", "0004_planning_rejected_at_planning_rejected_by_and_more"),
        ("surgeries", "0002_alter_intervention_options"),
    ]
    try:
        executor.migrate(prior)
        apps = executor.loader.project_state(prior).apps
        legacy = apps.get_model("plannings", "Planning")
        historical_surgery = apps.get_model("surgeries", "Surgery")
        specialty = apps.get_model("surgeries", "Specialty").objects.create(nombre="Especialidad histórica")
        staff = apps.get_model("surgeries", "MedicalStaff").objects.create(
            id=STAFF_2, nombre="Cirujano histórico", rol="cirujano",
        )
        room = apps.get_model("surgeries", "OperatingRoom").objects.create(id=ROOM_2, nombre="Quirófano 2")
        patient = apps.get_model("surgeries", "Patient").objects.create(
            dni="historico-1", nombre="Paciente histórico",
        )
        start = datetime(2032, 2, 2, 9, 0, tzinfo=UTC)
        end = start.replace(hour=10)
        surgery = historical_surgery.objects.create(
            estado="Programada", inicio=start, fin=end, sala=room,
            paciente=patient, especialidad=specialty, cirujano_forzado=staff,
        )
        original_supply = apps.get_model("surgeries", "Supply").objects.create(nombre="Compresas", stock=0)
        apps.get_model("surgeries", "SurgerySupply").objects.create(
            cirugia=surgery, insumo=original_supply, cantidad=30, observaciones="Esterilizadas",
        )
        payload = {
            "week_start": "2032-02-02", "operating_rooms": [{"id": 1, "name": "Quirófano 2"}],
            "id_maps": {
                "surgeries": {surgery.pk: 1}, "medical_staff": {STAFF_2: 1},
                "interventions": {PROC_GENERAL: 1}, "operating_rooms": {ROOM_2: 1},
            },
            "pending_surgeries": [{"id": 1, "forced_surgeon_id": 1}],
        }
        output = {"dias": [{"bloques": [{
            "quirofano": "Quirófano 2",
            "cronograma": [{"paciente_id": 1, "hora_inicio": "09:00", "hora_fin": "10:00"}],
        }]}]}
        approved = legacy.objects.create(
            scheduler_uuid="legacy-approved", input_payload=payload, output_payload=output,
            status="approved", approved_at=start, approved_by="historico@hospital.test",
        )
        pending = legacy.objects.create(
            scheduler_uuid="legacy-pending", input_payload=payload, output_payload=output, status="pending_approval",
        )
        rejected = legacy.objects.create(
            scheduler_uuid="legacy-rejected", status="rejected", input_payload=payload,
            output_payload=output, rejection_reason="Motivo histórico",
        )
        event = apps.get_model("plannings", "PlanningAuditEvent").objects.create(
            planning=approved, surgery=surgery, source="user",
            action="surgery_scheduled_from_planning", summary="Aprobada según circuito histórico",
        )
    finally:
        MigrationExecutor(connection).migrate(targets)

    live = Planning.objects.get(pk=approved.pk)
    assert live.week_start == date(2032, 2, 2)
    assert live.operational and live.applied_version.origin == "historical"
    assert live.input_payload == payload and live.output_payload == output
    assert live.approved_by == "historico@hospital.test"
    assert not PlanningVote.objects.filter(version__planning=live).exists()
    assert not Planning.objects.get(pk=pending.pk).operational
    assert Planning.objects.get(pk=rejected.pk).rejection_reason == "Motivo histórico"
    assert PlanningAuditEvent.objects.filter(pk=event.pk).exists()
    assert AppliedSurgery.objects.get(surgery_id=surgery.pk).planning == live
    assert Surgery.objects.get(pk=surgery.pk).inicio == start
    relation = SurgerySupply.objects.get(cirugia_id=surgery.pk)
    assert relation.insumo.nombre == "Compresas" and relation.cantidad == 30
