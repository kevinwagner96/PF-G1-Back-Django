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
| Administrador | admin@hospital.com | admin123 |
| Cirujano | cirujano@hospital.com | cirujano123 |
| Jefe Quirofano | jefe@hospital.com | jefe123 |
| Recepcionista | recepcion@hospital.com | recepcion123 |

El Front debe usar `NEXT_PUBLIC_API_BASE_URL=http://localhost:3010/api/v1` para compartir cookies de sesión con Django.

## Django Admin y roles

El admin se accede en `http://127.0.0.1:3010/admin/` con `admin@hospital.com / admin123`.

La demo usa grupos y permisos Django:

- `Administrador`: puede generar planificaciones.
- `Cirujano`: puede aprobar planificaciones completadas.
- `Jefe Quirofano` y `Recepcionista`: sin permisos de planificación por defecto.
