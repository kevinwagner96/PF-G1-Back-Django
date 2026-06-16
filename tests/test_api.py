import pytest
from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from accounts.permissions import (
    ACCESS_SYSTEM_ADMIN_PERMISSION,
    APPROVE_PLANNING_PERMISSION,
    CREATE_PLANNING_PERMISSION,
)
from plannings.models import Planning, PlanningAuditEvent
from surgeries.models import Surgery

pytestmark = pytest.mark.django_db


def test_login_and_me(client):
    user_model = get_user_model()
    user = user_model.objects.create_user(username="demo@hospital.com", email="demo@hospital.com", password="demo123", nombre="Demo", rol="Cirujano")
    response = client.post("/api/v1/auth/login/", {"email": user.email, "password": "demo123"}, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == user.email
    assert client.get("/api/v1/auth/me/").status_code == 200


def test_demo_seed_creates_groups_and_user_permissions(client):
    sysadmin = get_user_model().objects.get(email="sysadmin@hospital.com")
    admin = get_user_model().objects.get(email="admin@hospital.com")
    surgeon = get_user_model().objects.get(email="cirujano@hospital.com")

    assert Group.objects.filter(name="System Admin", user=sysadmin).exists()
    assert Group.objects.filter(name="Administrador", user=admin).exists()
    assert Group.objects.filter(name="Cirujano", user=surgeon).exists()
    assert sysadmin.is_staff is True
    assert sysadmin.is_superuser is True
    assert admin.is_staff is False
    assert admin.is_superuser is False

    client.force_login(sysadmin)
    sysadmin_permissions = client.get("/api/v1/auth/me/").json()["user"]["permissions"]
    assert ACCESS_SYSTEM_ADMIN_PERMISSION in sysadmin_permissions
    assert CREATE_PLANNING_PERMISSION not in sysadmin_permissions
    assert APPROVE_PLANNING_PERMISSION not in sysadmin_permissions

    client.force_login(admin)
    admin_permissions = client.get("/api/v1/auth/me/").json()["user"]["permissions"]
    assert CREATE_PLANNING_PERMISSION in admin_permissions
    assert APPROVE_PLANNING_PERMISSION not in admin_permissions
    assert ACCESS_SYSTEM_ADMIN_PERMISSION not in admin_permissions

    client.force_login(surgeon)
    surgeon_permissions = client.get("/api/v1/auth/me/").json()["user"]["permissions"]
    assert APPROVE_PLANNING_PERMISSION in surgeon_permissions
    assert CREATE_PLANNING_PERMISSION not in surgeon_permissions
    assert ACCESS_SYSTEM_ADMIN_PERMISSION not in surgeon_permissions


def test_callback_rejects_bad_token(client):
    response = client.post("/api/v1/scheduler/callback/", {"uuid": "missing", "status": "completed"}, content_type="application/json", HTTP_X_SCHEDULER_TOKEN="bad")
    assert response.status_code == 403


def test_surgeries_returns_seeded_demo_data(client):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)

    response = client.get("/api/v1/surgeries/")

    assert response.status_code == 200
    assert len(response.json()) == 20
    assert response.json()[0]["estado"] == "Pendiente"


def test_demo_reset_keeps_current_session(client):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)

    response = client.post("/api/v1/demo/reset/")

    assert response.status_code == 200
    assert client.get("/api/v1/auth/me/").status_code == 200


def test_create_planning_with_scheduler_mock(client, monkeypatch):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)

    def fake_scheduler(payload):
        assert len(payload["pending_surgeries"]) == 20
        assert payload["id_maps"]["surgeries"]
        return {
            "uuid": "11111111-2222-3333-4444-555555555555",
            "status": "planning",
            "progress_percentage": 0,
        }

    monkeypatch.setattr("plannings.views.request_scheduler_planning", fake_scheduler)

    response = client.post(
        "/api/v1/plannings/",
        {"week_start": "2026-06-15"},
        content_type="application/json",
    )

    assert response.status_code == 202
    assert response.json()["scheduler_uuid"] == "11111111-2222-3333-4444-555555555555"
    planning = Planning.objects.get(scheduler_uuid=response.json()["scheduler_uuid"])
    assert planning.status == "planning"
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.PLANNING_CREATED,
        planning=planning,
        actor=user,
    ).exists()
    assert LogEntry.objects.filter(object_pk=planning.id).exists()


def test_surgeon_cannot_create_planning(client, monkeypatch):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)

    monkeypatch.setattr("plannings.views.request_scheduler_planning", lambda payload: pytest.fail("Scheduler should not be called"))

    response = client.post(
        "/api/v1/plannings/",
        {"week_start": "2026-06-15"},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert Planning.objects.count() == 0


def test_create_planning_returns_clear_error_when_scheduler_response_has_no_uuid(
    client,
    monkeypatch,
):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)

    monkeypatch.setattr(
        "plannings.views.request_scheduler_planning",
        lambda payload: {"status": "planning"},
    )

    response = client.post(
        "/api/v1/plannings/",
        {"week_start": "2026-06-15"},
        content_type="application/json",
    )

    assert response.status_code == 502
    assert "missing uuid" in response.json()["detail"]


def test_valid_callback_updates_planning(client, settings):
    planning = Planning.objects.create(
        scheduler_uuid="22222222-2222-3333-4444-555555555555",
        status="planning",
        input_payload={"week_start": "2026-06-15"},
        started_at=timezone.now(),
    )

    response = client.post(
        "/api/v1/scheduler/callback/",
        {
            "uuid": planning.scheduler_uuid,
            "status": "completed",
            "output_payload": {"dias": []},
            "duration_seconds": 1.2,
        },
        content_type="application/json",
        HTTP_X_SCHEDULER_TOKEN=settings.SCHEDULER_CALLBACK_TOKEN,
    )

    planning.refresh_from_db()
    assert response.status_code == 200
    assert planning.status == "pending_approval"
    assert planning.progress_percentage == 100
    assert planning.output_payload == {"dias": []}
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.PLANNING_PENDING_APPROVAL,
        planning=planning,
        source=PlanningAuditEvent.Source.SCHEDULER,
    ).exists()


def test_failed_callback_creates_failed_audit_event(client, settings):
    planning = Planning.objects.create(
        scheduler_uuid="22222222-aaaa-3333-4444-555555555555",
        status="planning",
        input_payload={"week_start": "2026-06-15"},
        started_at=timezone.now(),
    )

    response = client.post(
        "/api/v1/scheduler/callback/",
        {
            "uuid": planning.scheduler_uuid,
            "status": "failed",
            "error_message": "No feasible schedule",
            "duration_seconds": 1.7,
        },
        content_type="application/json",
        HTTP_X_SCHEDULER_TOKEN=settings.SCHEDULER_CALLBACK_TOKEN,
    )

    planning.refresh_from_db()
    assert response.status_code == 200
    assert planning.status == "failed"
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.SCHEDULER_CALLBACK_FAILED,
        planning=planning,
        source=PlanningAuditEvent.Source.SCHEDULER,
        metadata__error_message="No feasible schedule",
    ).exists()


def test_approve_completed_planning_programs_surgery(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    surgery_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeee01"
    room_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
    planning = Planning.objects.create(
        scheduler_uuid="33333333-2222-3333-4444-555555555555",
        status="pending_approval",
        input_payload={
            "week_start": "2026-06-15",
            "operating_rooms": [{"id": 1, "name": "Quirófano 1"}],
            "id_maps": {
                "surgeries": {surgery_id: 1},
                "operating_rooms": {room_id: 1},
            },
        },
        output_payload={
            "dias": [
                {
                    "nombre": "Lunes",
                    "bloques": [
                        {
                            "quirofano": "Quirófano 1",
                            "turno": "Mañana",
                            "cronograma": [
                                {
                                    "paciente_id": 1,
                                    "hora_inicio": "08:00",
                                    "hora_fin": "10:00",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    response = client.post(f"/api/v1/plannings/{planning.scheduler_uuid}/approve/")

    surgery = Surgery.objects.get(id=surgery_id)
    planning.refresh_from_db()
    assert response.status_code == 200
    assert planning.status == "approved"
    assert surgery.estado == "Programada"
    assert surgery.sala_id == room_id
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.PLANNING_APPROVED,
        planning=planning,
        actor=user,
    ).exists()
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.SURGERY_SCHEDULED_FROM_PLANNING,
        planning=planning,
        surgery=surgery,
        actor=user,
    ).exists()
    assert LogEntry.objects.filter(object_pk=surgery.id).exists()


def test_admin_cannot_approve_pending_planning(client):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)
    planning = Planning.objects.create(
        scheduler_uuid="44444444-2222-3333-4444-555555555555",
        status="pending_approval",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.post(f"/api/v1/plannings/{planning.scheduler_uuid}/approve/")

    planning.refresh_from_db()
    assert response.status_code == 403
    assert planning.status == "pending_approval"
    assert not PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.PLANNING_APPROVED,
        planning=planning,
    ).exists()


def test_reject_pending_planning_with_reason_does_not_program_surgeries(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    surgery_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeee01"
    planning = Planning.objects.create(
        scheduler_uuid="66666666-2222-3333-4444-555555555555",
        status="pending_approval",
        input_payload={
            "week_start": "2026-06-15",
            "operating_rooms": [{"id": 1, "name": "Quirófano 1"}],
            "id_maps": {
                "surgeries": {surgery_id: 1},
                "operating_rooms": {"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1": 1},
            },
        },
        output_payload={
            "dias": [
                {
                    "nombre": "Lunes",
                    "bloques": [
                        {
                            "quirofano": "Quirófano 1",
                            "turno": "Mañana",
                            "cronograma": [
                                {
                                    "paciente_id": 1,
                                    "hora_inicio": "08:00",
                                    "hora_fin": "10:00",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    response = client.post(
        f"/api/v1/plannings/{planning.scheduler_uuid}/reject/",
        {"reason": "Necesita revisión de disponibilidad"},
        content_type="application/json",
    )

    planning.refresh_from_db()
    surgery = Surgery.objects.get(id=surgery_id)
    assert response.status_code == 200
    assert planning.status == "rejected"
    assert planning.rejected_by == user.email
    assert planning.rejection_reason == "Necesita revisión de disponibilidad"
    assert surgery.estado == "Pendiente"
    assert surgery.inicio is None
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.PLANNING_REJECTED,
        planning=planning,
        actor=user,
        metadata__reason="Necesita revisión de disponibilidad",
    ).exists()


def test_reject_pending_planning_requires_reason(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    planning = Planning.objects.create(
        scheduler_uuid="77777777-2222-3333-4444-555555555555",
        status="pending_approval",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.post(
        f"/api/v1/plannings/{planning.scheduler_uuid}/reject/",
        {"reason": ""},
        content_type="application/json",
    )

    planning.refresh_from_db()
    assert response.status_code == 400
    assert planning.status == "pending_approval"


def test_admin_cannot_reject_pending_planning(client):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)
    planning = Planning.objects.create(
        scheduler_uuid="88888888-2222-3333-4444-555555555555",
        status="pending_approval",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.post(
        f"/api/v1/plannings/{planning.scheduler_uuid}/reject/",
        {"reason": "No corresponde"},
        content_type="application/json",
    )

    planning.refresh_from_db()
    assert response.status_code == 403
    assert planning.status == "pending_approval"


def test_active_planning_returns_latest_active_planning(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    Planning.objects.create(
        scheduler_uuid="99999999-1111-3333-4444-555555555555",
        status="approved",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )
    active = Planning.objects.create(
        scheduler_uuid="99999999-2222-3333-4444-555555555555",
        status="pending_approval",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.get("/api/v1/plannings/active/")

    assert response.status_code == 200
    assert response.json()["scheduler_uuid"] == active.scheduler_uuid


def test_active_planning_returns_404_when_no_active_planning(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    Planning.objects.create(
        scheduler_uuid="99999999-3333-3333-4444-555555555555",
        status="rejected",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.get("/api/v1/plannings/active/")

    assert response.status_code == 404


def test_surgeon_cannot_delete_pending_planning(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    planning = Planning.objects.create(
        scheduler_uuid="99999999-4444-3333-4444-555555555555",
        status="pending_approval",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.delete(f"/api/v1/plannings/{planning.scheduler_uuid}/")

    assert response.status_code == 403
    assert Planning.objects.filter(id=planning.id).exists()


def test_delete_completed_planning_creates_audit_event(client):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)
    planning = Planning.objects.create(
        scheduler_uuid="55555555-2222-3333-4444-555555555555",
        status="completed",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )
    planning_id = planning.id

    response = client.delete(f"/api/v1/plannings/{planning.scheduler_uuid}/")

    assert response.status_code == 204
    assert not Planning.objects.filter(id=planning_id).exists()
    assert PlanningAuditEvent.objects.filter(
        action=PlanningAuditEvent.Action.PLANNING_DELETED,
        planning__isnull=True,
        actor=user,
        metadata__scheduler_uuid="55555555-2222-3333-4444-555555555555",
    ).exists()
