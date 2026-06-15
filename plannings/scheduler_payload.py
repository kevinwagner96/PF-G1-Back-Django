from collections import defaultdict
from typing import Any

from surgeries.models import Intervention, Surgery

SCHEDULER_DEFAULT_CONFIG: dict[str, int | float] = {
    "population_size": 50,
    "max_generations": 50,
    "convergence_patience": 7,
    "mutation_rate": 0.10,
    "crossover_rate": 0.85,
    "tournament_size": 10,
    "elite_count": 2,
    "alpha": 0.7,
    "beta": 0.3,
    "n_days": 5,
    "n_shifts": 2,
    "block_duration_min": 240,
    "slot_size_min": 15,
    "penalty_below_min_quota": 50.0,
    "penalty_above_max_quota": 20.0,
    "parallel_workers": 24,
}


def indexed_map(values: list[str]) -> dict[str, int]:
    return {value: index for index, value in enumerate(sorted(values), start=1)}


def first_intervention(surgery: Surgery) -> Intervention | None:
    items = list(surgery.intervenciones.all())
    return items[0].intervencion if items else None


def fallback_procedure_id(specialty_code: int) -> int:
    return specialty_code * 100


def build_staff_availability(disponibilidades) -> dict[str, list[int]]:
    return {
        str(item.dia): [item.inicio_minutos, item.fin_minutos]
        for item in sorted(disponibilidades, key=lambda value: value.dia)
    }


def build_scheduler_payload(*, week_start: str, pending_surgeries, operating_rooms, medical_staff, specialties, interventions) -> dict[str, Any]:
    specialty_map = indexed_map([specialty.id for specialty in specialties])
    room_map = indexed_map([room.id for room in operating_rooms])
    staff_map = indexed_map([staff.id for staff in medical_staff])
    intervention_map = indexed_map([intervention.id for intervention in interventions])
    surgery_map = indexed_map([surgery.id for surgery in pending_surgeries])

    procedures_by_specialty: dict[int, set[int]] = defaultdict(set)
    for intervention in interventions:
        if intervention.especialidad_id is None:
            continue
        specialty_code = specialty_map.get(intervention.especialidad_id)
        procedure_code = intervention_map.get(intervention.id)
        if specialty_code is not None and procedure_code is not None:
            procedures_by_specialty[specialty_code].add(procedure_code)

    for specialty_code in specialty_map.values():
        if not procedures_by_specialty.get(specialty_code):
            procedures_by_specialty[specialty_code].add(fallback_procedure_id(specialty_code))

    return {
        "week_start": week_start,
        "pending_surgeries": [
            to_scheduler_surgery(surgery, specialty_map, staff_map, intervention_map, surgery_map)
            for surgery in pending_surgeries
        ],
        "operating_rooms": [
            {
                "id": room_map[room.id],
                "name": room.nombre,
                "or_type": room.tipo_quirofano,
                "availability": room.disponibilidad,
            }
            for room in operating_rooms
        ],
        "specialties": [
            {"id": 0, "name": "Libre", "compatible_or_types": [], "min_blocks": 0, "max_blocks": 99},
            *[
                {
                    "id": specialty_map[specialty.id],
                    "name": specialty.nombre,
                    "compatible_or_types": specialty.compatible_tipos_quirofano,
                    "min_blocks": specialty.min_bloques,
                    "max_blocks": specialty.max_bloques,
                }
                for specialty in specialties
            ],
        ],
        "medical_staff": [
            {
                "id": staff_map[staff.id],
                "name": staff.nombre,
                "role": staff.rol,
                "enabled_procedures_ids": sorted(
                    {
                        procedure_id
                        for specialty in staff.especialidades.all()
                        for procedure_id in procedures_by_specialty.get(specialty_map.get(specialty.id, -1), set())
                    }
                ),
                "availability_hours": build_staff_availability(staff.disponibilidades.all()),
            }
            for staff in medical_staff
        ],
        "procedures_by_specialty": {
            str(specialty_code): sorted(procedure_ids)
            for specialty_code, procedure_ids in procedures_by_specialty.items()
        },
        "id_maps": {
            "specialties": specialty_map,
            "operating_rooms": room_map,
            "medical_staff": staff_map,
            "interventions": intervention_map,
            "surgeries": surgery_map,
        },
        "config": SCHEDULER_DEFAULT_CONFIG,
    }


def to_scheduler_surgery(surgery: Surgery, specialty_map, staff_map, intervention_map, surgery_map) -> dict[str, Any]:
    specialty_code = specialty_map[surgery.especialidad_id]
    intervention = first_intervention(surgery)
    procedure_id = intervention_map[intervention.id] if intervention is not None else fallback_procedure_id(specialty_code)
    return {
        "id": surgery_map[surgery.id],
        "source_id": surgery.id,
        "specialty_id": specialty_code,
        "procedure_id": procedure_id,
        "estimated_duration": surgery.duracion_estimada_minutos,
        "clinical_priority": surgery.prioridad_clinica,
        "forced_surgeon_id": staff_map.get(surgery.cirujano_forzado_id) if surgery.cirujano_forzado_id else None,
    }
