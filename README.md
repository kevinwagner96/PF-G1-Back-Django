# PF-G1 Back Django

Backend nuevo de PF-G1 implementado desde cero con Django REST Framework.

## Ejecutar local

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:3010
```

Si se necesita regenerar datos demo para ver reportes y cirugias con sentido:

```bash
.venv/bin/python manage.py shell -c "from demo.seed import seed_demo_data; seed_demo_data()"
```

## Levantar PostgreSQL local

El repo incluye un compose sólo para la base Django. Usa el puerto `5433` para no chocar con
la base vieja del Back.

```bash
docker compose up -d db
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:3010
```

## Demo

Usuarios:

| Rol | Email | Password |
| --- | --- | --- |
| System Admin | sysadmin@hospital.com | sysadmin123 |
| Administrador | admin@hospital.com | admin123 |
| Cirujano | cirujano@hospital.com | cirujano123 |
| Jefe Quirofano | jefe@hospital.com | jefe123 |
| Recepcionista | recepcion@hospital.com | recepcion123 |

El Front debe usar `NEXT_PUBLIC_API_BASE_URL=http://localhost:3010/api/v1` para compartir cookies de sesión con Django.

La semilla demo incluye usuarios, grupos, permisos, cirugias pendientes para planificacion y cirugias historicas/programadas/canceladas para los indicadores de reportes.

## Django Admin y roles

El admin se accede en `http://127.0.0.1:3010/admin/` con `sysadmin@hospital.com / sysadmin123`.

La demo usa grupos y permisos Django:

- `System Admin`: acceso técnico a Django Admin.
- `Administrador`: puede generar planificaciones.
- `Cirujano`: puede revisar planificaciones pendientes, aprobarlas o rechazarlas con motivo.
- `Jefe Quirofano` y `Recepcionista`: sin permisos de planificación por defecto.

## API MVP

- `GET /api/v1/surgeries/`: listado de cirugias para el MVP.
- `POST /api/v1/plannings/`: genera una planificacion y llama al Scheduler desde el Back.
- `GET /api/v1/plannings/active/`: devuelve la planificacion activa mas reciente en estado `planning` o `pending_approval`.
- `POST /api/v1/scheduler/callback/`: recibe el resultado del Scheduler. Cuando llega `completed`, la planificacion queda como `pending_approval`.
- `POST /api/v1/plannings/{scheduler_uuid}/approve/`: aprueba una planificacion pendiente y recien ahi programa cirugias como `Programada`.
- `POST /api/v1/plannings/{scheduler_uuid}/reject/`: rechaza una planificacion pendiente con motivo obligatorio, sin modificar cirugias.
- `GET /api/v1/reports/summary/`: devuelve reportes en tiempo real desde las tablas. Acepta `date_from=YYYY-MM-DD` y `date_to=YYYY-MM-DD`.

Los reportes MVP exponen solo tres indicadores: utilizacion de quirofanos, tasa de cancelacion y tiempo promedio de espera.
