import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from accounts.permissions import APPROVE_PLANNING_PERMISSION, CREATE_PLANNING_PERMISSION
from plannings.models import Planning
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
    admin = get_user_model().objects.get(email="admin@hospital.com")
    surgeon = get_user_model().objects.get(email="cirujano@hospital.com")

    assert Group.objects.filter(name="Administrador", user=admin).exists()
    assert Group.objects.filter(name="Cirujano", user=surgeon).exists()

    client.force_login(admin)
    admin_permissions = client.get("/api/v1/auth/me/").json()["user"]["permissions"]
    assert CREATE_PLANNING_PERMISSION in admin_permissions
    assert APPROVE_PLANNING_PERMISSION not in admin_permissions

    client.force_login(surgeon)
    surgeon_permissions = client.get("/api/v1/auth/me/").json()["user"]["permissions"]
    assert APPROVE_PLANNING_PERMISSION in surgeon_permissions
    assert CREATE_PLANNING_PERMISSION not in surgeon_permissions


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
    assert Planning.objects.get(scheduler_uuid=response.json()["scheduler_uuid"]).status == "planning"


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
    assert planning.status == "completed"
    assert planning.progress_percentage == 100
    assert planning.output_payload == {"dias": []}


def test_approve_completed_planning_programs_surgery(client):
    user = get_user_model().objects.get(email="cirujano@hospital.com")
    client.force_login(user)
    surgery_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeee01"
    room_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
    planning = Planning.objects.create(
        scheduler_uuid="33333333-2222-3333-4444-555555555555",
        status="completed",
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


def test_admin_cannot_approve_completed_planning(client):
    user = get_user_model().objects.get(email="admin@hospital.com")
    client.force_login(user)
    planning = Planning.objects.create(
        scheduler_uuid="44444444-2222-3333-4444-555555555555",
        status="completed",
        input_payload={"week_start": "2026-06-15"},
        output_payload={"dias": []},
    )

    response = client.post(f"/api/v1/plannings/{planning.scheduler_uuid}/approve/")

    planning.refresh_from_db()
    assert response.status_code == 403
    assert planning.status == "completed"
