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
DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:3010
.venv/bin/python manage.py check
.venv/bin/pytest
.venv/bin/ruff check .
```

## Validación local del Django Admin

- Para validar `/admin/` fuera de Docker, levantar con `DJANGO_DEBUG=true`; si no, el admin puede verse como texto plano porque `runserver` no sirve estáticos con `DEBUG=false`.
- Abrir `http://127.0.0.1:3010/admin/` e ingresar con `sysadmin@hospital.com / sysadmin123`.
- Si el admin carga sin CSS/JS, revisar primero que el proceso se haya levantado con `DJANGO_DEBUG=true`.
- En Docker/Gunicorn con `DJANGO_DEBUG=false`, si el admin aparece en texto plano, falta configurar `collectstatic` y servir `/static/`.

## Flujo principal

- El Front nunca llama al Scheduler.
- La autorización funcional usa permisos explícitos por grupo, no el texto de `User.rol`.
- `System Admin` es técnico y entra a Django Admin; `Administrador` es funcional y genera planificaciones desde el Front.
- `POST /api/v1/plannings/` crea una planificación y llama a `pf-or-scheduler`.
- `GET /api/v1/plannings/{scheduler_uuid}/` devuelve estado persistido y sincroniza progreso si sigue planificando.
- `GET /api/v1/plannings/active/` devuelve la planificación activa más reciente en `planning` o `pending_approval`.
- `POST /api/v1/scheduler/callback/` recibe el resultado completo del Scheduler y valida `X-Scheduler-Token`; si llega `completed`, se guarda como `pending_approval` para revisión humana.
- `POST /api/v1/plannings/{scheduler_uuid}/approve/` marca cirugías como `Programada` sólo si la planificación está en `pending_approval` y el usuario tiene `plannings.can_approve_planning`.
- `POST /api/v1/plannings/{scheduler_uuid}/reject/` rechaza una planificación pendiente con motivo obligatorio y no modifica cirugías.
- `GET /api/v1/reports/summary/` calcula reportes en tiempo real desde las tablas, sin mocks ni agregados persistidos.
- `POST /api/v1/demo/reset/` borra planificaciones, devuelve cirugías demo a `Pendiente` y conserva datos demo suficientes para reportes.

## Reglas para agentes

- Usar migraciones Django, no scripts SQL sueltos ni Alembic.
- Mantener autenticación por sesión Django, cookies y CSRF.
- Gestionar roles demo con `Group` y `Permission` desde Django Admin.
- Proteger el callback con `X-Scheduler-Token`.
- No convertir cirugías a `Programada` salvo por aprobación explícita.
- Mantener payloads JSON completos en `Planning.input_payload` y `Planning.output_payload` para auditoría.
- Mantener reportes MVP acotados a tres indicadores: utilización de quirófanos, tasa de cancelación y tiempo promedio de espera.
- Mantener sólo endpoints Django canónicos con slash final; no reintroducir aliases legacy.
