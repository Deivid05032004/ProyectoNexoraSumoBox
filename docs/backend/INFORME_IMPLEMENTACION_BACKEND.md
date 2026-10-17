# Auditoría del backend UTA SUMO ROBOTICS CUP

Fecha: 16 de octubre de 2026  
Rama verificada: `feature/backend-core`

## Estado

El backend local está operativo con FastAPI, SQL Server Express y JWT. Las
migraciones 06–09 fueron aplicadas sin eliminar los registros existentes. El
esquema ya usa email cifrado más índice HMAC, Argon2id, campos sensibles cifrados
con AES-GCM, comprobantes cifrados y autorización por propietario/rol. Los
listados de alto volumen usan paginación SQL `OFFSET/FETCH`, límite máximo de 100,
conteos y metadatos de paginación; los resúmenes se agregan dentro de SQL.

## Rutas principales

| Grupo | Rutas |
| --- | --- |
| Salud | `/`, `/api/v1/health`, `/api/v1/health/live` |
| Auth | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/google`, `POST /api/v1/auth/google/link`, `GET /api/v1/auth/me`, `POST /api/v1/auth/change-password` |
| Catálogos | `/api/v1/categories`, `/api/v1/institutions`, `/api/v1/events`, `/api/v1/tariffs` |
| Recursos | `/api/v1/teams`, `/api/v1/robots`, `/api/v1/participants` |
| Inscripciones | `/api/v1/registrations`, `/{id}`, `/code/{uuid}`, `/{id}/history`, `/{id}/review`, `/{id}/cancel` |
| Pagos | `/api/v1/payments`, `/{id}`, `/{id}/receipt`, `/{id}/review` |
| Administración | `/api/v1/admin/roles`, `/users`, `/users/{id}`, `/dashboard`, `/audit/users` |
| Reportes | `/api/v1/reports/overview`, `registrations/by-status`, `by-category`, `trend`, `registrations/details`, `payments/summary`, `payments/details` |

Los reportes detallados responden con `items`, `page`, `page_size`, `total` y
`total_pages`. Las listas exponen `X-Total-Count`, `X-Page`, `X-Page-Size` y
`X-Total-Pages`; CORS expone esos encabezados para el frontend.

## Flujos y seguridad

- Registro pide email, comprueba formato y DNS/MX del dominio, crea rol
  `PARTICIPANT` y perfil de participante en una transacción. No verifica que la
  persona controle el buzón.
- Google login/link valida firma, emisor, expiración, audiencia e email verificado
  con `google-auth`; la identidad se vincula por el `sub` estable. La migración
  09 crea `UserExternalIdentities`. Las rutas responden 503 hasta configurar
  `GOOGLE_CLIENT_ID`; una prueba real requiere Google Cloud y cliente frontend.
- Google login/link se limita a `PARTICIPANT`. El frontend ofrece Google solo
  en la pantalla de participantes; `/admin` usa correo y contraseña. El script
  manual de cuentas privilegiadas aplica la misma política fuerte de contraseña
  que el registro público.
- La contraseña requiere 15 caracteres como mínimo, se hashea con Argon2id y
  nunca se almacena en claro. Los hashes bcrypt heredados se verifican y migran
  al iniciar sesión.
- Emails cifrados se buscan por HMAC. Nombres, teléfonos, notas, comentarios,
  referencias de pago y comprobantes se cifran con AES-GCM.
- Inscripción, participantes asociados, pago inicial e historial se crean de
  forma atómica. El pago y el estado de inscripción avanzan en transacciones y
  cada cambio queda en historial.
- Participantes solo consultan sus recursos; ADMIN/REVIEWER/TREASURY tienen
  permisos separados. Los reportes financieros no incluyen la referencia de
  transferencia ni datos personales.
- `SECRET_KEY` y `PII_ENCRYPTION_KEY` son locales, están ignoradas por Git y
  deben conservarse protegidas para restaurar datos cifrados.

## SQL y scripts

- `database/scripts/01_create_database.sql` a `05_create_constraints.sql`:
  esquema canónico para una instalación nueva.
- `database/scripts/06_email_encryption_upgrade.sql` y
  `07_email_encryption_constraints.sql`: backfill y restricciones de email.
- `database/scripts/08_pagination_indexes.sql`: índices de orden/filtro para
  listados y reportes detallados.
- `database/scripts/09_google_identities.sql`: mapeo único de proveedor y subject.
- `backend/uta_sumo_api/scripts/migrate.py`: aplica cada migración en una
  transacción y guarda su checksum. El modo normal no elimina datos.
- `bootstrap_local_demo_accounts.py`: crea automáticamente perfiles demo locales
  después de migrar si `AUTO_BOOTSTRAP_DEMO_ACCOUNTS=true`. Las claves son
  aleatorias, se imprimen al crearse y no son recuperables desde SQL.
- `provision_operator_user.py`: crea usuarios privilegiados a petición del
  operador, con password oculto y email validado.
- Postman: `UTA_Sumo_API.postman_collection.json` para explorar rutas y
  `UTA_Sumo_E2E.postman_collection.json` para el flujo de extremo a extremo.
- Frontend `frontend/uta-sumo-web`: `/inscripcion` y `/participante` permiten
  registro/login; `/admin` usa credenciales privilegiadas.

## Verificación ejecutada

- Suite SQL Server antes de las últimas restricciones de rol y el refactor de
  política de contraseñas: **18 passed**; no se volvió a ejecutar tras esos
  cambios.
- Build de producción Vite después de integrar las pantallas de acceso: correcto.
- Newman/Postman: **21 solicitudes y 21 aserciones aprobadas**. Cubre login por
  rol, equipo, robot, inscripción, pagos, comprobante cifrado, transiciones,
  reportes agregados/detallados y denegación por rol.
- Newman/Postman registro/login: registro HTTP 201 y login HTTP 200 con correo
  válido; cuenta de smoke test eliminada al terminar.
- Migración normal repetida sin cambios destructivos; migración 09 aplicada.
- Inspección de SQL: cuatro cuentas, una por rol, índice único HMAC presente y
  sin plaintext en las columnas sensibles comprobadas.

Comandos desde `backend/uta_sumo_api`:

```powershell
.venv\Scripts\python.exe scripts\migrate.py
$env:RUN_SQLSERVER_TESTS = '1'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\bootstrap_local_demo_accounts.py --run-postman
```

Si las cuentas demo ya existen y no se conocen sus contraseñas, `--rotate-existing`
las cambia por claves nuevas antes de ejecutar Newman.

## Pendientes reales antes de producción

1. Configurar Client ID real en `.env` del backend y frontend, orígenes y
   consentimiento OAuth; correr prueba E2E con Google. El código de interfaz,
   backend y migración están listos, pero falta el Client ID.
2. Verificación de propiedad de email con enlace/código para registro local.
3. Rate limiting distribuido y defensa contra intentos automatizados de login.
4. Cifrado de volumen, logs y backups. SQL Server Express no dispone de TDE;
   el cifrado de campos de la aplicación no cifra el archivo MDF ni los backups.
5. Gestor de secretos y procedimiento probado de rotación de `PII_ENCRYPTION_KEY`.
6. Análisis antivirus/contenido real de comprobantes; actualmente se valida
   tamaño, MIME, extensión y firma inicial.
7. Certificado SQL válido en producción con `DB_TRUST_SERVER_CERTIFICATE=no`.
8. Política automatizada de retención, backups y pruebas de restauración.
9. Exportación CSV/XLSX no implementada: los reportes están disponibles como
   JSON paginado y agregado.

Los detalles anteriores son condiciones de endurecimiento para producción; la
API local y sus rutas probadas funcionan. La guía integral está en
`GUIA_COMPLETA_BACKEND.md`. No se crearon commits ni pushes.
