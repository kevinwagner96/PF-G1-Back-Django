from surgeries.models import MedicalStaff, OperatingRoom, Surgery


def build_planning_preflight() -> dict:
    pending_surgeries = (
        Surgery.objects.filter(estado="Pendiente")
        .select_related("paciente", "especialidad", "cirujano_forzado")
        .prefetch_related(
            "intervenciones__intervencion",
            "cirujano_forzado__especialidades",
            "cirujano_forzado__disponibilidades",
        )
        .order_by("-prioridad_clinica", "created_at")
    )
    invalid_surgeries = []

    for surgery in pending_surgeries:
        reasons = []
        intervention_items = list(surgery.intervenciones.all())
        interventions = [item.intervencion for item in intervention_items]

        if not interventions:
            reasons.append("No tiene intervenciones cargadas")
        if surgery.duracion_estimada_minutos <= 0:
            reasons.append("La duración estimada debe ser mayor a cero")
        if surgery.prioridad_clinica <= 0:
            reasons.append("La prioridad clínica debe ser mayor a cero")
        if not surgery.especialidad.estado:
            reasons.append("La especialidad está inactiva")
        if any(not intervention.estado for intervention in interventions):
            reasons.append("Tiene intervenciones inactivas")
        if any(intervention.especialidad_id != surgery.especialidad_id for intervention in interventions):
            reasons.append("Tiene intervenciones de otra especialidad")
        surgeon = surgery.cirujano_forzado
        if surgeon is None:
            reasons.append("No tiene un cirujano asignado")
        elif not surgeon.estado or surgeon.rol.lower() != "cirujano":
            reasons.append("El cirujano asignado no está disponible como cirujano activo")
        else:
            if not surgeon.especialidades.filter(id=surgery.especialidad_id, estado=True).exists():
                reasons.append("El cirujano asignado no pertenece a la especialidad de la cirugía")
            has_suitable_window = any(
                item.dia in range(5)
                and max(item.inicio_minutos, 480) + surgery.duracion_estimada_minutos
                <= min(item.fin_minutos, 780)
                for item in surgeon.disponibilidades.all()
            )
            if not has_suitable_window:
                reasons.append("El cirujano no tiene una franja entre 08:00 y 13:00 donde quepa la cirugía")

        if reasons:
            invalid_surgeries.append(
                {
                    "id": surgery.id,
                    "paciente": surgery.paciente.nombre,
                    "dni": surgery.paciente.dni,
                    "reasons": reasons,
                }
            )

    pending_count = pending_surgeries.count()
    valid_count = pending_count - len(invalid_surgeries)
    blocking_reasons = []

    if pending_count == 0:
        blocking_reasons.append("No hay cirugías pendientes para planificar")
    if invalid_surgeries:
        blocking_reasons.append("Hay cirugías pendientes con datos incompletos o inválidos")

    available_operating_rooms_count = OperatingRoom.objects.filter(disponible=True).count()
    available_surgeons_count = (
        MedicalStaff.objects.filter(estado=True, rol__iexact="cirujano", disponibilidades__isnull=False)
        .distinct()
        .count()
    )

    if available_operating_rooms_count == 0:
        blocking_reasons.append("No hay quirófanos disponibles")
    if available_surgeons_count == 0:
        blocking_reasons.append("No hay cirujanos activos con disponibilidad cargada")

    return {
        "pending_count": pending_count,
        "valid_count": valid_count,
        "can_plan": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "invalid_surgeries": invalid_surgeries,
        "resources": {
            "available_operating_rooms_count": available_operating_rooms_count,
            "available_surgeons_count": available_surgeons_count,
        },
    }
