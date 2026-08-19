from datetime import date, datetime, time, timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from surgeries.models import OperatingRoom, Surgery

SHIFT_DURATION_MINUTES = 240


class ReportRangeSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        today = timezone.localdate()
        date_to = attrs.get("date_to") or today
        date_from = attrs.get("date_from") or date_to - timedelta(days=29)
        if date_from > date_to:
            raise serializers.ValidationError("date_from no puede ser posterior a date_to")
        attrs["date_from"] = date_from
        attrs["date_to"] = date_to
        return attrs


class ReportsSummaryView(APIView):
    def get(self, request):
        serializer = ReportRangeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        date_from = serializer.validated_data["date_from"]
        date_to = serializer.validated_data["date_to"]

        started_from = timezone.make_aware(datetime.combine(date_from, time.min))
        started_to = timezone.make_aware(datetime.combine(date_to, time.max))
        surgeries = Surgery.objects.filter(inicio__gte=started_from, inicio__lte=started_to)

        effective_surgeries = surgeries.exclude(estado="Cancelada")
        room_details, utilization_percentage = build_operating_room_utilization(
            date_from=date_from,
            date_to=date_to,
            surgeries=effective_surgeries,
        )
        total_surgeries = surgeries.count()
        cancelled_surgeries = surgeries.filter(estado="Cancelada").count()
        cancellation_rate = (
            round(cancelled_surgeries * 100 / total_surgeries, 2)
            if total_surgeries
            else 0.0
        )
        wait_days_by_specialty, average_wait_days = build_wait_days_by_specialty(effective_surgeries)
        surgeries_by_specialty = build_surgeries_by_specialty(surgeries)
        surgeries_by_day = build_surgeries_by_day(
            date_from=date_from,
            date_to=date_to,
            surgeries=surgeries,
        )

        return Response(
            {
                "generated_at": timezone.now(),
                "range": {
                    "date_from": date_from,
                    "date_to": date_to,
                },
                "operating_room_utilization": {
                    "value": utilization_percentage,
                    "unit": "percent",
                    "label": "Utilización de quirófanos",
                },
                "cancellation_rate": {
                    "value": cancellation_rate,
                    "unit": "percent",
                    "label": "Tasa de cancelación",
                },
                "average_wait_days": {
                    "value": average_wait_days,
                    "unit": "days",
                    "label": "Tiempo promedio de espera",
                },
                "details": {
                    "operating_rooms": room_details,
                    "statuses": list(
                        surgeries.values("estado")
                        .annotate(count=Count("id"))
                        .order_by("estado")
                    ),
                    "wait_by_specialty": wait_days_by_specialty,
                    "surgeries_by_specialty": surgeries_by_specialty,
                    "surgeries_by_day": surgeries_by_day,
                },
            }
        )


def daterange(date_from: date, date_to: date):
    current = date_from
    while current <= date_to:
        yield current
        current += timedelta(days=1)


def available_minutes_for_room(room: OperatingRoom, date_from: date, date_to: date) -> int:
    availability = room.disponibilidad or []
    total = 0
    for day in daterange(date_from, date_to):
        weekday = day.weekday()
        if weekday >= len(availability):
            continue
        total += sum(1 for shift_available in availability[weekday] if shift_available)
    return total * SHIFT_DURATION_MINUTES


def build_operating_room_utilization(*, date_from: date, date_to: date, surgeries) -> tuple[list[dict], float]:
    details = []
    total_scheduled_minutes = 0
    total_available_minutes = 0

    for room in OperatingRoom.objects.filter(disponible=True).order_by("nombre"):
        available_minutes = available_minutes_for_room(room, date_from, date_to)
        scheduled_minutes = 0
        room_surgeries = surgeries.filter(sala=room, inicio__isnull=False, fin__isnull=False)
        for surgery in room_surgeries:
            scheduled_minutes += int((surgery.fin - surgery.inicio).total_seconds() // 60)
        utilization = (
            round(scheduled_minutes * 100 / available_minutes, 2)
            if available_minutes
            else 0.0
        )
        total_scheduled_minutes += scheduled_minutes
        total_available_minutes += available_minutes
        details.append(
            {
                "room": room.nombre,
                "scheduled_minutes": scheduled_minutes,
                "available_minutes": available_minutes,
                "utilization_percentage": utilization,
            }
        )

    overall_utilization = (
        round(total_scheduled_minutes * 100 / total_available_minutes, 2)
        if total_available_minutes
        else 0.0
    )
    return details, overall_utilization


def build_wait_days_by_specialty(surgeries) -> tuple[list[dict], float]:
    grouped: dict[str, list[int]] = {}
    wait_values = []
    for surgery in surgeries.select_related("especialidad"):
        if surgery.inicio is None:
            continue
        wait_days = max((surgery.inicio.date() - surgery.created_at.date()).days, 0)
        wait_values.append(wait_days)
        grouped.setdefault(surgery.especialidad.nombre, []).append(wait_days)

    details = [
        {
            "specialty": specialty,
            "average_wait_days": round(sum(values) / len(values), 2),
            "surgeries_count": len(values),
        }
        for specialty, values in sorted(grouped.items())
    ]
    average_wait_days = round(sum(wait_values) / len(wait_values), 2) if wait_values else 0.0
    return details, average_wait_days


def build_surgeries_by_specialty(surgeries) -> list[dict]:
    rows = (
        surgeries.values("especialidad__nombre")
        .annotate(count=Count("id"))
        .order_by("-count", "especialidad__nombre")
    )
    return [
        {"specialty": row["especialidad__nombre"] or "Sin especialidad", "count": row["count"]}
        for row in rows
    ]


def build_surgeries_by_day(*, date_from: date, date_to: date, surgeries) -> list[dict]:
    counts_by_date: dict[date, int] = {}
    for surgery in surgeries:
        if surgery.inicio is None:
            continue
        surgery_date = surgery.inicio.date()
        counts_by_date[surgery_date] = counts_by_date.get(surgery_date, 0) + 1

    return [
        {"date": day.isoformat(), "count": counts_by_date.get(day, 0)}
        for day in daterange(date_from, date_to)
    ]
