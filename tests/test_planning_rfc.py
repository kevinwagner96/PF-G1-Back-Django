from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client

from demo.seed import GENERAL, PROC_GENERAL, ROOM_1, ROOM_2, STAFF_2, TRAUMA
from plannings.models import (
    Planning,
    PlanningAuditEvent,
    PlanningEditLock,
    PlanningVersion,
    SpecialtyChief,
)
from surgeries.models import Surgery, SurgeryCancellation

pytestmark = pytest.mark.django_db

WEEK = "2030-06-17"
ADMIN = "admin@hospital.com"
SURGEON = "cirujano@hospital.com"
CHIEF = "jefe@hospital.com"


def login_as(client, email):
    client.force_login(get_user_model().objects.get(email=email))
    return client


def as_user(email):
    return login_as(Client(), email)


def post(client, url, data):
    return client.post(url, data, content_type="application/json")


def url(uuid, suffix=""):
    return f"/api/v1/plannings/{uuid}/{suffix}"


def callback(settings, uuid, output=None, outcome="completed"):
    return Client().post(
        "/api/v1/scheduler/callback/",
        {"uuid": uuid, "status": outcome, "output_payload": output, "error_message": "Fallo de prueba"},
        content_type="application/json", HTTP_X_SCHEDULER_TOKEN=settings.SCHEDULER_CALLBACK_TOKEN,
    )


def booked(agenda, surgery_ids_with_slots):
    days = [{"bloques": []} for _ in range(5)]
    codes = agenda.input_payload["id_maps"]["surgeries"]
    for surgery, day, room, hour, minute in surgery_ids_with_slots:
        start = datetime(2030, 6, 17 + day, hour, minute)
        end = start + timedelta(minutes=surgery.duracion_estimada_minutos)
        days[day]["bloques"].append({"quirofano": room, "cronograma": [{
            "paciente_id": codes[surgery.pk], "hora_inicio": start.time().isoformat(),
            "hora_fin": end.time().isoformat(),
        }]})
    return {"dias": days, "resumen": {"caso": "prueba"}}


@pytest.fixture
def dispatched(monkeypatch):
    calls = []

    def submit(payload):
        assert Planning.objects.filter(
            scheduler_uuid=payload["job_uuid"], operational=True, week_start=payload["week_start"],
        ).exists()
        calls.append(payload)
        return {"uuid": payload["job_uuid"], "status": "planning"}

    monkeypatch.setattr("plannings.views.request_scheduler_planning", submit)
    return calls


def request_plan(client, week=WEEK):
    return post(client, "/api/v1/plannings/", {"week_start": week})


def accept_proposal(settings, uuid, output):
    response = callback(settings, uuid, output)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval", Planning.objects.get(scheduler_uuid=uuid).error_message


def vote(client, uuid, number=1):
    return post(client, url(uuid, "approve/"), {"version": number})


def all_chiefs():
    return list(SpecialtyChief.objects.select_related("user").order_by("pk"))


def approve(uuid, number=1, exclude_user=None):
    result = None
    for chief in all_chiefs():
        if chief.user.email == exclude_user:
            continue
        response = vote(as_user(chief.user.email), uuid, number)
        assert response.status_code == 200, response.json()
        result = response.json()
    assert result is not None and result["status"] == "approved"
    return result


def acquire(client, uuid, number=1, urgent=False):
    return post(client, url(uuid, "lock/"), {"version": number, "urgent": urgent})


def edit(client, uuid, lock, ops, *, reason="Ajuste de prueba", **extra):
    return post(client, url(uuid, "edit/"), {**lock, "operations": ops, "reason": reason, **extra})


@pytest.fixture
def scenario(settings, dispatched):
    admin = as_user(ADMIN)
    started = request_plan(admin)
    assert started.status_code == 202, started.json()
    uuid = started.json()["scheduler_uuid"]
    planning = Planning.objects.get(scheduler_uuid=uuid)
    trauma = Surgery.objects.filter(estado="Pendiente", especialidad_id=TRAUMA).first()
    general = Surgery.objects.filter(estado="Pendiente", especialidad_id=GENERAL).first()
    output = booked(planning, [
        (trauma, 0, "Quirófano 1", 9, 0),
        (general, 1, "Quirófano 2", 9, 0),
    ])
    accept_proposal(settings, uuid, output)
    return admin, uuid, trauma, general, output


def test_uniqueness_failed_retry_and_late_callback(client, settings, dispatched):
    assert request_plan(login_as(client, SURGEON)).status_code == 403
    login_as(client, ADMIN)
    assert request_plan(client, "2030-06-18").status_code == 400
    first = request_plan(client)
    assert first.status_code == 202
    uuid = first.json()["scheduler_uuid"]
    assert request_plan(client).status_code == 409
    assert len(dispatched) == 1
    assert callback(settings, uuid, outcome="failed").status_code == 200
    second = request_plan(client)
    assert second.status_code == 202 and second.json()["scheduler_uuid"] != uuid
    assert callback(settings, uuid, {"dias": []}).json()["status"] == "failed"
    new_uuid = second.json()["scheduler_uuid"]
    accept_proposal(settings, new_uuid, {"dias": [{"bloques": []} for _ in range(5)]})
    assert request_plan(client).status_code == 409
    assert request_plan(client, "2030-06-24").status_code == 202
    lookup = client.get(f"/api/v1/plannings/?week_start={WEEK}").json()
    assert lookup["planning"]["scheduler_uuid"] == new_uuid
    assert {item["status"] for item in lookup["attempts"]} == {"failed", "pending_approval"}
    assert client.delete(url(new_uuid)).status_code == 405
    assert post(client, url(new_uuid, "reject/"), {"reason": "Obsoleto"}).status_code == 404


def test_callback_race_with_polling_preserves_result(scenario, settings, monkeypatch):
    admin, uuid, trauma, _, output = scenario
    lock = acquire(admin, uuid).json()
    assert edit(admin, uuid, lock, [{"kind": "remove", "surgery_id": trauma.pk}]).status_code == 200
    assert callback(settings, uuid, output).json()["status"] == "pending_approval"
    monkeypatch.setattr("plannings.views.request_scheduler_status", lambda _: pytest.fail("Already received callback"))
    detail = admin.get(url(uuid)).json()
    assert detail["current_version"]["number"] == 2
    assert trauma.pk not in detail["current_version"]["assignments"]
    assert detail["output_payload"] == output


def test_failed_poll_has_audited_retry(scenario, monkeypatch):
    admin, _, _, _, _ = scenario
    other = request_plan(admin, "2030-06-24").json()["scheduler_uuid"]
    monkeypatch.setattr("plannings.views.request_scheduler_status", lambda _: {"status": "completed"})
    assert admin.get(url(other)).json()["progress_percentage"] == 100
    Planning.objects.filter(scheduler_uuid=other).update(updated_at=datetime.now(UTC) - timedelta(seconds=8))
    assert admin.get(url(other)).json()["status"] == "failed"
    assert request_plan(admin, "2030-06-24").status_code == 202


def test_consensus_and_replacement_of_chief(scenario):
    admin, uuid, trauma, _, _ = scenario
    assert vote(admin, uuid).status_code == 403
    assert vote(as_user(SURGEON), uuid).status_code == 403
    original = SpecialtyChief.objects.get(specialty_id=TRAUMA)
    assert vote(as_user(CHIEF), uuid).json()["status"] == "pending_approval"
    substitute = get_user_model().objects.get(email=SURGEON)
    substitute.groups.add(*original.user.groups.all())
    original.user = substitute
    original.save(update_fields=["user"])
    for chief in all_chiefs():
        if chief.user.email != SURGEON:
            assert vote(as_user(chief.user.email), uuid).json()["status"] == "pending_approval"
    assert Surgery.objects.get(pk=trauma.pk).estado == "Pendiente"
    assert vote(as_user(CHIEF), uuid).status_code == 403
    applied = vote(as_user(SURGEON), uuid).json()
    assert applied["status"] == "approved"
    assert len(applied["current_version"]["votes"]) == 7
    assert Surgery.objects.get(pk=trauma.pk).estado == "Programada"


def test_edit_lock_permissions_noop_recovery_and_logout(scenario):
    admin, uuid, _, general, _ = scenario
    chief = as_user(CHIEF)
    other_session = as_user(CHIEF)
    lock = acquire(chief, uuid).json()
    assert acquire(other_session, uuid).status_code == 409
    assert vote(chief, uuid).status_code == 409
    assert edit(chief, uuid, lock, [{"kind": "remove", "surgery_id": general.pk}]).status_code == 403
    recovered = post(admin, url(uuid, "lock/recover/"), {"reason": "Sesión abandonada"})
    assert recovered.status_code == 200
    assert edit(chief, uuid, lock, []).status_code == 409
    assert vote(chief, uuid).status_code == 200
    lock = acquire(admin, uuid).json()
    result = edit(admin, uuid, lock, [], reason="")
    assert result.json()["current_version"]["number"] == 1
    assert len(result.json()["current_version"]["votes"]) == 1
    acquire(chief, uuid)
    assert chief.post("/api/v1/auth/logout/").status_code == 204
    assert not PlanningEditLock.objects.exists()
    history = admin.get(url(uuid, "history/")).json()
    assert any(event["action"] == "lock_recovered" for event in history["events"])


def test_ordinary_edit_applies_only_after_new_votes_and_retirement_is_not_cancel(scenario):
    admin, uuid, trauma, general, _ = scenario
    approve(uuid)
    chief = as_user(CHIEF)
    lock = acquire(chief, uuid).json()
    response = edit(chief, uuid, lock, [{"kind": "remove", "surgery_id": trauma.pk}])
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["status"] == "pending_approval"
    assert data["applied_version"]["number"] == 1
    assert data["current_version"]["number"] == 2
    assert len(data["current_version"]["votes"]) == 1
    assert data["effective_assignments"][trauma.pk]
    assert acquire(admin, uuid, 2, urgent=True).status_code == 409
    assert vote(as_user("jefe.2@hospital.com"), uuid, 1).status_code == 409
    approve(uuid, 2, exclude_user=CHIEF)
    trauma.refresh_from_db()
    assert (trauma.estado, trauma.inicio, trauma.fin, trauma.sala_id) == ("Pendiente", None, None, None)
    assert not SurgeryCancellation.objects.filter(surgery=trauma).exists()
    assert post(admin, f"/api/v1/surgeries/{general.pk}/cancel/", {"reason": "Decisión clínica"}).status_code == 200
    report = admin.get(f"/api/v1/reports/summary/?date_from={WEEK}&date_to=2030-06-21").json()
    assert report["cancellation_rate"]["value"] == 100.0
    assert report["details"]["statuses"] == [{"estado": "Cancelada", "count": 1}]


@pytest.mark.parametrize("move_existing", [False, True])
def test_urgency_atomically_registers_patient_and_applies(scenario, move_existing):
    admin, uuid, trauma, general, _ = scenario
    approve(uuid)
    assert acquire(as_user(SURGEON), uuid, urgent=True).status_code == 403
    chief = as_user(CHIEF)
    lock = acquire(chief, uuid, urgent=True).json()
    emergency = {
        "provisional_name": "Paciente provisional", "intervention_ids": [PROC_GENERAL],
        "cirujano_forzado_id": STAFF_2, "duracion_estimada_minutos": 30, "prioridad_clinica": 9,
        "room_id": ROOM_2, "starts_at": f"{'2030-06-18' if move_existing else WEEK}T09:00:00Z",
    }
    if move_existing:
        count = Surgery.objects.count()
        bad = edit(chief, uuid, lock, [], emergency=emergency)
        assert bad.status_code == 400 and "solapamiento" in bad.json()["detail"]
        assert Surgery.objects.count() == count
    operations = [{"kind": "remove", "surgery_id": general.pk}] if move_existing else []
    result = edit(chief, uuid, lock, operations, emergency=emergency)
    assert result.status_code == 200, result.json()
    detail = result.json()
    assert detail["status"] == "approved"
    assert detail["current_version"]["origin"] == "urgent"
    assert detail["current_version"]["votes"] == []
    assert detail["effective_assignments"][trauma.pk]
    current = Surgery.objects.get(pk=detail["current_version"]["urgent_surgery_id"])
    assert current.estado == "Programada" and current.paciente.dni.startswith("PROV-")
    if move_existing:
        assert Surgery.objects.get(pk=general.pk).estado == "Pendiente"
    audit = admin.get(url(uuid, "history/")).json()
    assert any(event["action"] == "urgency_applied" for event in audit["events"])


def test_invalid_batch_leaves_version_and_audit_intact(scenario, monkeypatch):
    admin, uuid, trauma, general, _ = scenario
    lock = acquire(admin, uuid).json()
    invalid = edit(admin, uuid, lock, [{"kind": "swap", "surgery_id": trauma.pk, "other_surgery_id": general.pk}])
    assert invalid.status_code == 400
    assert "incompatible" in invalid.json()["detail"]
    assert PlanningVersion.objects.count() == 1
    new_slot = {"kind": "move", "surgery_id": general.pk, "room_id": ROOM_2, "starts_at": f"{WEEK}T11:00:00Z"}

    def fail_audit(*args, **kwargs):
        raise RuntimeError("Falló auditoría")

    with monkeypatch.context() as patched:
        patched.setattr("plannings.agenda.audit", fail_audit)
        with pytest.raises(RuntimeError, match="Falló auditoría"):
            edit(admin, uuid, lock, [new_slot])
    assert PlanningVersion.objects.count() == 1
    assert PlanningEditLock.objects.count() == 1
    saved = edit(admin, uuid, lock, [new_slot])
    assert saved.status_code == 200, saved.json()
    assert saved.json()["current_version"]["votes"] == []
    assert PlanningAuditEvent.objects.filter(action="version_saved").count() == 1


def test_replace_swap_and_assign_use_each_surgery_duration(scenario):
    admin, uuid, trauma, general, _ = scenario
    replacement, spare, new_case = list(
        Surgery.objects.filter(estado="Pendiente", especialidad_id=GENERAL).exclude(
            pk=general.pk,
        ).order_by("duracion_estimada_minutos")[:3],
    )
    lock = acquire(admin, uuid).json()
    edits = [
        {"kind": "replace", "surgery_id": general.pk, "other_surgery_id": replacement.pk},
        {"kind": "assign", "surgery_id": spare.pk, "room_id": ROOM_2, "starts_at": "2030-06-20T09:15:00Z"},
        {"kind": "assign", "surgery_id": new_case.pk, "room_id": ROOM_1, "starts_at": "2030-06-21T09:00:00Z"},
    ]
    response = edit(admin, uuid, lock, edits)
    assert response.status_code == 200, response.json()
    assignments = response.json()["current_version"]["assignments"]
    assert general.pk not in assignments and trauma.pk in assignments
    assert assignments[replacement.pk]["starts_at"] == "2030-06-18T09:00:00+00:00"
    response = edit(admin, uuid, acquire(admin, uuid, 2).json(), [
        {"kind": "swap", "surgery_id": spare.pk, "other_surgery_id": new_case.pk},
    ])
    assert response.status_code == 200, response.json()
    version_three = response.json()["current_version"]["assignments"]
    for surgery, target in ((spare, new_case), (new_case, spare)):
        assignment = version_three[surgery.pk]
        assert assignment["starts_at"] == assignments[target.pk]["starts_at"]
        assert assignment["room_id"] == assignments[target.pk]["room_id"]
        duration = datetime.fromisoformat(assignment["ends_at"]) - datetime.fromisoformat(assignment["starts_at"])
        assert duration.total_seconds() == surgery.duracion_estimada_minutos * 60


def test_supply_detail_round_trip_and_catalog(scenario):
    admin, _, _, _, _ = scenario
    body = {
        "patient": {"dni": "68542901", "nombre": "Paciente de prueba"},
        "intervention_ids": [PROC_GENERAL], "cirujano_forzado_id": STAFF_2,
        "duracion_estimada_minutos": 60, "prioridad_clinica": 3,
        "insumos": [{"nombre": "Apósitos", "cantidad": 12500, "observaciones": "Estériles"}],
    }
    created = post(admin, "/api/v1/surgeries/", body)
    assert created.status_code == 201
    surgery_url = f"/api/v1/surgeries/{created.json()['id']}/"
    detail = admin.get(surgery_url).json()["insumos"][0]
    assert {key: detail[key] for key in body["insumos"][0]} == body["insumos"][0]
    catalog = admin.get("/api/v1/surgery-catalogs/").json()["supplies"]
    assert {"id": detail["insumo_id"], "nombre": "Apósitos"} in catalog
    body["insumos"] = [{"insumo_id": detail["insumo_id"], "cantidad": 7}]
    updated = admin.patch(surgery_url, body, content_type="application/json")
    assert updated.json()["insumos"][0]["cantidad"] == 7


@pytest.mark.django_db(transaction=True)
def test_postgres_serializes_generation_and_edit_lock(settings, dispatched):
    if connection.vendor != "postgresql":
        pytest.skip("Requiere PostgreSQL para probar bloqueos de filas")

    def parallel(call):
        barrier = Barrier(2)

        def worker():
            try:
                remote = as_user(ADMIN)
                barrier.wait(timeout=10)
                return call(remote).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(future.result(timeout=20) for future in [pool.submit(worker), pool.submit(worker)])

    assert parallel(request_plan) == [202, 409]
    assert len(dispatched) == 1
    uuid = dispatched[0]["job_uuid"]
    accept_proposal(settings, uuid, {"dias": [{"bloques": []} for _ in range(5)]})
    assert parallel(lambda client: acquire(client, uuid)) == [200, 409]
