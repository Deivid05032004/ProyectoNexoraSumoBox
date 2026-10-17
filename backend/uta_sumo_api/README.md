# Backend UTA SUMO ROBOTICS CUP

API REST con FastAPI, SQLAlchemy y SQL Server. Swagger UI: `/docs`; OpenAPI:
`/openapi.json`.

## Windows y configuración

1. Desde `backend/uta_sumo_api`, crea el entorno si no existe:
   `py -3.14 -m venv .venv`
2. Instala runtime y pruebas: `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
3. Copia `.env.example` de la raíz a `backend/uta_sumo_api/.env` si aún no existe.
4. Define `SECRET_KEY` aleatoria de al menos 32 caracteres y `PII_ENCRYPTION_KEY` como base64url de 32 bytes aleatorios. No cambies ni pierdas estas claves después de cifrar datos. La instancia local usa Windows Auth, `.`\`SQLEXPRESS`, base
   `UTA_SUMO_ROBOTICS_CUP` y ODBC Driver 18.
5. Ejecuta las migraciones aditivas: `.venv\Scripts\python.exe scripts\migrate.py`.
   Conservan los datos y crean cuentas demo locales para cada rol.
6. Inicia desde este directorio:
   `.venv\Scripts\python.exe -m uvicorn main:app --reload`
7. Abre `http://127.0.0.1:8000/docs`.

El archivo `.env` local está ignorado por Git. Conserva `SECRET_KEY` y `PII_ENCRYPTION_KEY` fuera del repositorio y de SQL; se necesitan para restaurar backups cifrados. Cambiar la clave PII requiere re-cifrar los datos. Para SQL Auth configura
`DB_AUTH_MODE=sql`, `DB_USERNAME` y `DB_PASSWORD`. `CORS_ORIGINS` acepta una
lista separada por comas. El comodín `*` se rechaza cuando se permiten
credenciales.

## Auth y permisos

Registro público requiere correo validado y asigna `PARTICIPANT`; nunca acepta el rol enviado por cliente. El login usa el correo. Se valida el formato y la disponibilidad DNS del dominio, pero esto no confirma que el usuario controle el buzón. Las contraseñas requieren al menos 15 caracteres y se almacenan con Argon2id; bcrypt solo se conserva para verificar hashes antiguos. Los JWT usan HS256 y expiran en 30 minutos por defecto. No hay refresh token. Los roles del sistema son `ADMIN`, `EVENT_MANAGER` y `PARTICIPANT`; la migración crea cuentas demo locales automáticamente y las cuentas reales se aprovisionan por operador.

También existe `POST /api/v1/auth/google` para inicio/registro con un ID token
verificado de Google y `POST /api/v1/auth/google/link` para vincular una cuenta
autenticada. Añade `GOOGLE_CLIENT_ID` al `.env` y configura Google Identity
Services en el cliente para habilitarlo. La API no recibe ni almacena la
contraseña de Google. El ID token debe venir de Google y coincidir con la
audiencia del Client ID configurado. La migración 09 crea la tabla de identidad
externa. Consulta la [guía completa del backend](../../docs/backend/GUIA_COMPLETA_BACKEND.md)
para configuración, flujos, rutas, roles, modelo de datos y pasos de despliegue.

Para crear una cuenta privilegiada de forma interactiva, ejecuta desde este
directorio `.venv\Scripts\python.exe scripts\provision_operator_user.py`.
El script solicita rol y contraseña oculta, no muestra ni guarda la contraseña
en texto plano y no crea usuarios predeterminados.

## Operación

- `ADMIN`: administra catálogos, usuarios y roles; puede revisar pagos e
  inscripciones y acceder a reportes financieros.
- `EVENT_MANAGER`: gestiona el flujo operativo, rondas, enfrentamientos,
  estados de competencia, puntuaciones y reportes operativos. No puede revisar
  pagos ni descargar comprobantes.
- `PARTICIPANT`: crea equipos/robots propios, inscripciones, presenta pagos y
  consulta exclusivamente sus datos privados; resultados publicados son públicos.

La migración 10 reasigna las cuentas antiguas `REVIEWER` a `EVENT_MANAGER` y
`TREASURY` a `ADMIN`; la migración 12 actualiza referencias de auditoría y
elimina roles obsoletos conservando los registros. Revise las cuentas `TREASURY`
antes de desplegar, porque el modelo nuevo limita las operaciones financieras
a `ADMIN`.

## Competencias y puntuación en vivo

La migración 10 agrega ciclo de vida `DRAFT → SCHEDULED → LIVE ↔ PAUSED →
FINISHED` con cancelación en preparación/ejecución, rondas, enfrentamientos y
movimientos append-only de puntos. La migración 11 agrega auditoría del estado
con usuario, fecha y motivo; la 12 finaliza la migración de roles. Son aditivas;
no eliminan registros operativos.

`PATCH /api/v1/events/{id}/competition-status` admite cambios de estado por
`ADMIN` y `EVENT_MANAGER`; cada transición queda en el historial. El personal
puede crear rondas (`POST /api/v1/events/{id}/rounds`) y enfrentamientos
(`POST /api/v1/events/{id}/matches`). Para puntuar, la competencia debe estar
`LIVE` y el equipo debe tener una inscripción `APPROVED` en el evento y
categoría correctos. `POST /api/v1/events/{id}/scores` agrega un movimiento
positivo o un ajuste negativo con motivo; se exige el header UUID
`Idempotency-Key` para que reintentos no dupliquen puntos. Nunca se sobrescriben
los movimientos previos y el total no puede ser negativo. No se impone un
reglamento deportivo: los empates se conservan con el mismo puesto.

Resultados, clasificación e historial público se consultan con
`GET /api/v1/events/{id}/leaderboard` y
`GET /api/v1/events/{id}/scores/history`. Las listas son paginadas desde SQL.
La bitácora completa de autoría para el personal se consulta con
`GET /api/v1/events/{id}/scores/audit`; el historial público no revela la
identidad interna del operador.
El WebSocket `ws://127.0.0.1:8000/api/v1/events/{id}/live` envía una instantánea
inicial y detecta cambios mediante consulta periódica cada dos segundos; emite
solo estado y clasificación, sin datos personales o financieros. El sondeo
funciona con una instancia de API y SQL Server persistente; varias instancias
pueden consultar la misma base, aunque el intervalo de actualización es de dos
segundos.

Una inscripción se identifica de forma única por evento, categoría, equipo y
robot. Un equipo puede tener varios robots y participar en más de una categoría
o evento, pero no duplicar el mismo robot en la misma categoría/evento. Cada
inscripción tiene un único pago, que puede recibir varios comprobantes durante
reenvíos tras rechazo; el historial del archivo anterior se conserva.

El flujo es `PAYMENT_PENDING` → `PAYMENT_REVIEW` → (pago `PAID`) `PENDING` →
`APPROVED`, `OBSERVED` o `REJECTED`. Si ADMIN rechaza un pago, vuelve a
`PAYMENT_PENDING`. Cada cambio se guarda en `StatusHistory`.

## Comprobantes

Se aceptan PDF, PNG y JPEG con MIME, extensión y firma inicial compatibles.
El límite por defecto es 5 MiB (`MAX_RECEIPT_BYTES`, hasta 20 MiB). El nombre
de almacenamiento es UUID y los archivos no se sirven como estáticos. El modo
implementado guarda en `RECEIPT_STORAGE_DIR`, por defecto
`backend/uta_sumo_api/storage/receipts/`, que está ignorado por Git. Para
producción configura un volumen privado fuera del directorio web y respalda
metadatos y archivos juntos. Los comprobantes se cifran con AES-GCM antes de almacenarse y solo se descifran para una descarga autorizada. No hay verificación bancaria automática.

## Reportes

`GET /api/v1/reports/overview` entrega KPIs agregados por evento (inscripciones,
aprobaciones, pendientes y pagos). `/registrations/by-status`,
`/registrations/by-category` y `/registrations/trend` respaldan gráficos y
tablas de operación; la tendencia acepta `from_date` y `to_date` en formato
ISO. `/payments/summary` muestra recuentos e importes agrupados por estado.
`/registrations/details` y `/payments/details` entregan filas operativas
paginadas, con conteo total en la respuesta y sin incluir datos de contacto ni
referencias bancarias. `ADMIN` consulta todos; `EVENT_MANAGER` ve datos de
inscripción y `ADMIN` datos financieros. Las listas aplican paginación SQL
con `page` y `limit` (máximo 100), y devuelven `X-Total-Count`, `X-Page`,
`X-Page-Size` y `X-Total-Pages`; los resúmenes se agregan en SQL antes de
responder.

## SQL Server

El modelo fuente está en `database/scripts/01_create_database.sql` a
`09_google_identities.sql`; las tablas, relaciones, índices y restricciones
son el esquema completo para una instalación nueva. El seed
`database/seeds/02_initial_data.sql` agrega los roles, estados y categoría base.
El esquema incluye propiedad de recursos, perfiles vinculados a usuarios,
versionado de sesión, metadata de comprobantes y auditoría de seguridad.

El ejecutor `scripts/migrate.py` aplica los lotes `GO`, abre una transacción por
migración, guarda su SHA-256 y rechaza que se edite una migración ya aplicada.
Para una base nueva ejecuta `scripts/migrate.py`. `--reset-local --confirm-drop`
recrea solo la instancia local de desarrollo y elimina todos sus datos; verifica
el destino antes de usarlo. La creación inicial de la base es el único
paso que SQL Server ejecuta fuera de una transacción explícita; las migraciones
de esquema y semillas se aplican dentro de transacciones.

Para levantar datos sintéticos locales y cuatro identidades de prueba:

```powershell
.venv\Scripts\python.exe scripts\bootstrap_local_demo_accounts.py --run-postman
```

La opción `--run-postman` utiliza Newman con la colección
`postman/UTA_Sumo_E2E.postman_collection.json`; el archivo temporal de variables
con contraseñas se elimina al terminar. Si las cuentas ya existen, no se pueden recuperar sus claves: usa `--rotate-existing --run-postman` para rotarlas y ejecutar Newman. Las claves aleatorias solo se muestran al crearlas
al crearlas y nunca se guardan en SQL o en los scripts. No hay cuentas
privilegiadas con contraseñas por defecto compartidas.

Las migraciones 06 a 12 se aplicaron en la instancia local. Se preservaron las cuentas y se cifraron sus datos personales; las filas históricas sin propietario no se exponen a participantes. Las migraciones son aditivas y no eliminan datos operativos. SQL Server Express no ofrece TDE, por lo que el cifrado de aplicación no cifra páginas, log ni backups completos. Protege el volumen y los backups con cifrado del sistema/almacenamiento o usa una edición con TDE.

## Pruebas

Pruebas unitarias: `.venv\Scripts\python.exe -m pytest -q`.
Las pruebas de SQL Server usan una transacción externa que siempre se revierte:

```powershell
$env:RUN_SQLSERVER_TESTS = '1'
.venv\Scripts\python.exe -m pytest -q
```

Los TestClient usan `httpx2`, que es el backend recomendado por la versión
instalada de Starlette. La suite SQL necesita SQL Server y los roles/estados
semilla; al ejecutarse, crea cuentas y datos únicamente dentro de la transacción
revertida.

## Postman

Importa `postman/UTA_Sumo_API.postman_collection.json` y
`postman/UTA_Sumo_Local.postman_environment.json`. Define `participantEmail`
con un correo real cuyo dominio tenga DNS/MX válido y una contraseña de al menos
15 caracteres; ejecuta `Registrar participante` y luego usa `Login`. Para las
cuentas demo, completa los valores de email y contraseña que imprime el
aprovisionador local. Crea institución, categoría, evento y tarifa como ADMIN. Copia los IDs en el entorno; inicia sesión para obtener los tokens por
rol. La petición de comprobante permite elegir localmente un PDF/PNG/JPEG.
La carpeta `Reportes` contiene solicitudes para resumen ejecutivo, estados,
categorías, tendencia mensual y pagos, con tokens separados por rol.
Para el flujo autenticado completo importa también
`postman/UTA_Sumo_E2E.postman_collection.json`; completa los nombres y claves
que imprimió el aprovisionador y usa los IDs de demostración del mismo paso.
La política de datos está en [backend-security-and-migrations.md](../../docs/backend-security-and-migrations.md).
