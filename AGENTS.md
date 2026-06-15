# AGENTS.md

## Contexto

Backend actual de PF-G1 creado desde cero con Django REST Framework. Este proyecto no incorpora compatibilidad con el backend anterior ni debe agregar frameworks o capas de persistencia alternativas.

## Stack

- Django 5
- Django REST Framework
- PostgreSQL con `psycopg`
- `django-cors-headers`
- `httpx` para llamar al Scheduler
- `pytest-django` y `ruff`

## Comandos

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:3010
.venv/bin/python manage.py check
.venv/bin/pytest
.venv/bin/ruff check .
```

## Flujo principal

- El Front nunca llama al Scheduler.
- La autorización funcional usa permisos explícitos por grupo, no el texto de `User.rol`.
- `POST /api/v1/plannings/` crea una planificación y llama a `pf-or-scheduler`.
- `GET /api/v1/plannings/{scheduler_uuid}/` devuelve estado persistido y sincroniza progreso si sigue planificando.
- `POST /api/v1/scheduler/callback/` recibe el resultado completo del Scheduler y valida `X-Scheduler-Token`.
- `POST /api/v1/plannings/{scheduler_uuid}/approve/` marca cirugías como `Programada` sólo si el usuario tiene rol `Cirujano`.
- `POST /api/v1/demo/reset/` borra planificaciones y devuelve cirugías demo a `Pendiente`.

## Reglas para agentes

- Usar migraciones Django, no scripts SQL sueltos ni Alembic.
- Mantener autenticación por sesión Django, cookies y CSRF.
- Gestionar roles demo con `Group` y `Permission` desde Django Admin.
- Proteger el callback con `X-Scheduler-Token`.
- No convertir cirugías a `Programada` salvo por aprobación explícita.
- Mantener payloads JSON completos en `Planning.input_payload` y `Planning.output_payload` para auditoría.
- Mantener sólo endpoints Django canónicos con slash final; no reintroducir aliases legacy.
