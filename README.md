# UTA SUMO ROBOTICS CUP

Proyecto web para gestionar participantes, inscripciones, pagos, eventos y marcador de competencia. Incluye frontend React, API FastAPI y esquema SQL Server.

## Inicio rápido con Docker Compose

1. Instala Docker Engine con Compose v2 (o Docker Desktop en Windows).
2. Copia `.env.example` a `.env`, configura los secretos y selecciona la edición/licencia de SQL Server.
3. Ejecuta `docker compose up --build -d`.
4. Abre `http://localhost:8080`.
5. Crea el primer usuario administrador con `docker compose run --rm migrate python scripts/provision_operator_user.py`.

Para un servidor público con dominio y HTTPS, configura DNS, `PUBLIC_DOMAIN`, Google OAuth, `CORS_ORIGINS` y una edición SQL Server licenciada; luego ejecuta `docker compose --profile production up --build -d`.

La guía de instalación, configuración, migración, respaldo y operación está en [docs/DESPLIEGUE_DOCKER_COMPOSE.md](docs/DESPLIEGUE_DOCKER_COMPOSE.md).

No subas `.env` al repositorio. Conserva la misma `PII_ENCRYPTION_KEY` para los datos existentes y respalda los volúmenes persistentes.
