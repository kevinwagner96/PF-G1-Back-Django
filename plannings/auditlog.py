from auditlog.registry import auditlog

from plannings.models import Planning
from surgeries.models import (
    AnesthesiaType,
    Intervention,
    MedicalStaff,
    MedicalStaffAvailability,
    OperatingRoom,
    Patient,
    Specialty,
    Supply,
    Surgery,
    SurgeryIntervention,
    SurgerySupply,
)


def _register(model: type) -> None:
    if model in auditlog._registry:
        return
    auditlog.register(model)


def register_auditlog_models() -> None:
    for model in (
        Planning,
        Surgery,
        Patient,
        Specialty,
        Intervention,
        OperatingRoom,
        MedicalStaff,
        MedicalStaffAvailability,
        AnesthesiaType,
        Supply,
        SurgeryIntervention,
        SurgerySupply,
    ):
        _register(model)
