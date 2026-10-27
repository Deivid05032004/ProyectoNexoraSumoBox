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
   Conservan los datos y, con `AUTO_BOOTSTRAP_DEMO_ACCOUNTS=true`, crean
   cuentas demo locales para cada rol y la cuenta ADMIN local
   `adminTics@uta.edu.ec`.
6. Inicia desde este directorio:
   `.venv\Scripts\python.exe -m uvicorn main:app --reload`
7. Abre `http://127.0.0.1:8000/docs`.

El archivo `.env` local está ignorado por Git. Conserva `SECRET_KEY` y `PII_ENCRYPTION_KEY` fuera del repositorio y de SQL; se necesitan para restaurar backups cifrados. Cambiar la clave PII requiere re-cifrar los datos. Para SQL Auth configura
`DB_AUTH_MODE=sql`, `DB_USERNAME` y `DB_PASSWORD`. `CORS_ORIGINS` acepta una
lista separada por comas. El comodín `*` se rechaza cuando se permiten
credenciales. Para desarrollo local permite `localhost` y `127.0.0.1` en los
puertos `5173` y `5174`; configura los orígenes de producción explícitamente.

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
en texto plano y no crea usuarios predeterminados. La única cuenta de acceso
predeterminada se crea por el aprovisionador local de demostración descrito
abajo; no debe habilitarse en servidores compartidos o productivos.

## Operación

- `ADMIN`: administra catálogos, usuarios y roles; puede revisar pagos e
  inscripciones y acceder a reportes financieros.
- `EVENT_MANAGER`: gestiona el flujo operativo, rondas, enfrentamientos,
  estados de competencia, puntuaciones y reportes operativos. No puede revisar
  pagos ni descargar comprobantes.
- `PARTICIPANT`: crea equipos/robots propios, inscripciones, presenta pagos y
  consulta exclusivamente sus datos privados; resultados publicados son públicos.

## Contrato del formulario de inscripción

El responsable de una inscripción se obtiene del JWT autenticado; el backend no
agrega automáticamente la cuenta responsable al roster. El formulario envía
`POST /api/v1/registrations` con `event_id`, `category_id`, `team_id`,
`robot_id` y un arreglo `participants`. Los límites de participantes y coaches
se configuran en `EventCategories`, por evento y categoría; la API no codifica
la política por nombre. Para UTA SUMO ROBOTICS CUP 2026, Mini Sumo Amateur RC
requiere exactamente dos integrantes `role: "PARTICIPANT"` y un coach; la
migración posterior 25 prevalece sobre la regla anterior de la migración 23.
Otros eventos pueden definir límites diferentes, hasta 30 posiciones.
Cada integrante puede enviar un `participant_id` ya vinculado
explícitamente a la misma cuenta, o sus datos `first_name`, `last_name`,
`institution_id` y `mobile_phone` (use `null` cuando no tenga celular). Los
perfiles nuevos se guardan sin asociarlos a una cuenta, y sus datos personales
se cifran antes de persistirlos. La posición determina `PARTICIPANT_1`,
`PARTICIPANT_2` o `COACH` y se conserva en `RegistrationParticipants`.

Ejemplo de roster completo:

```json
{
  "event_id": 1,
  "category_id": 1,
  "team_id": 1,
  "robot_id": 1,
  "participants": [
    {"role": "PARTICIPANT", "first_name": "Ana", "last_name": "Pérez", "institution_id": 1, "mobile_phone": "0990000001"},
    {"role": "PARTICIPANT", "first_name": "Luis", "last_name": "Mora", "institution_id": 1, "mobile_phone": null},
    {"role": "COACH", "first_name": "María", "last_name": "Vega", "institution_id": 1, "mobile_phone": "0990000003"}
  ],
  "notes": null
}
```

El formulario frontend actual debe consumir `GET /api/v1/events/{event_id}/categories`
para construir el roster dinámico y validar esos límites; debe dejar de mostrar
un coach cuando la regla del evento indique `max_coaches: 0`. Los límites se
validan de nuevo en backend. En ambos formatos el backend calcula la tarifa,
crea exactamente un pago `PENDING` y registra inscripción, roster, pago e
historial dentro de una transacción SQL. Los IDs de participante existentes
solo se aceptan si pertenecen explícitamente a la cuenta autenticada.

Un administrador configura la relación evento/categoría con
`PUT /api/v1/admin/events/{event_id}/categories/{category_id}` enviando
`is_active`, `min_participants`, `max_participants`, `min_coaches`,
`max_coaches` y opcionalmente `max_registrations`. La creación de una tarifa
activa también vincula esa categoría al evento con reglas generales por
defecto. La migración 22 conserva asociaciones ya usadas por tarifas o
inscripciones; la 23 instala los límites del evento oficial 2026 sin cambiar
inscripciones ni pagos históricos.

`GET /api/v1/registrations/my?page=1&limit=50` devuelve las inscripciones
persistidas del participante autenticado, con código, evento, categoría,
equipo, robot, integrantes en orden, estado, importe, estado del pago y si el
comprobante puede presentarse. `GET /api/v1/payments/my?page=1&limit=50`
devuelve las órdenes existentes e indica `can_upload_receipt`, `has_receipt` y
el estado de inscripción. Ninguna consulta crea órdenes. Ambos endpoints
filtran por el usuario del token y aplican paginación SQL; la API conserva
también los endpoints de listado existentes.

El detalle individual se consulta con `GET /api/v1/registrations/{id}` y
`GET /api/v1/payments/{id}`. Para subir o volver a subir un comprobante después
del rechazo, reutilice `POST /api/v1/payments/{payment_id}/receipt`; el pago
pasa a `IN_REVIEW`, sin marcarse como `PAID`. El administrador registra la
decisión en `POST /api/v1/payments/{payment_id}/review`. Los estados y la
habilitación de carga se recalculan al consultar nuevamente.

El panel ADMIN también puede suscribirse a
`ws://127.0.0.1:8000/api/v1/payments/ws/admin` (en HTTPS, `wss://`). La conexión
requiere un JWT activo de rol `ADMIN`, enviado como segundo subprotocolo junto a
`uta-payment-updates`; el servidor negocia únicamente el nombre del protocolo.
Al crear una inscripción de equipo, cambiar su estado, cargar un comprobante o
revisar un pago se transmite un evento mínimo con IDs y estados, además de la
hora del comprobante cuando aplica; nunca se envía el archivo ni datos personales. El
frontend vuelve a consultar las inscripciones al conectarse y al recibir un
evento, reconecta si pierde el socket y reconcilia cada 30 segundos por si un
cambio se realizó fuera de la API. El broadcast actual es local al proceso; si
se despliega con varios workers, se requiere un broker compartido para repartir
eventos entre procesos.

La migración 10 reasigna las cuentas antiguas `REVIEWER` a `EVENT_MANAGER` y
`TREASURY` a `ADMIN`; la migración 12 actualiza referencias de auditoría y
elimina roles obsoletos conservando los registros. Revise las cuentas `TREASURY`
antes de desplegar, porque el modelo nuevo limita las operaciones financieras
a `ADMIN`.

## Competencias y puntuación en vivo

La migración 13 agrega `RegistrationPosition` para preservar el orden de
Participante 1, Participante 2 y Coach sin reinterpretar los registros
históricos ambiguos. Las posiciones previas solo se completan cuando el roster
histórico es inequívoco.

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

El modelo fuente está en `database/scripts/01_create_database.sql` y las
migraciones aditivas `10` a `20`; las tablas, relaciones, índices y restricciones
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

Para aprovisionar cuatro identidades locales de prueba (el evento, categoría y
tarifa siempre se toman de las migraciones; no se crea un evento demo):

```powershell
.venv\Scripts\python.exe scripts\bootstrap_local_demo_accounts.py --run-postman
```

El mismo bootstrap local crea, solo si aún no existe, la cuenta ADMIN
`adminTics@uta.edu.ec` con contraseña inicial `Admin@utaTics`. La cuenta se
conserva en ejecuciones posteriores y el script no restablece su contraseña.
Es una credencial fija de desarrollo, corta respecto de la política general
de 15 caracteres y solo se crea cuando el servidor SQL es local y la base
es `UTA_SUMO_ROBOTICS_CUP`. No uses esa clave en un servidor compartido o
productivo. Después del primer acceso, cámbiala desde
`POST /api/v1/auth/change-password` por una frase de 15 caracteres o más.
La migración local ejecuta este aprovisionamiento al finalizar cuando
`AUTO_BOOTSTRAP_DEMO_ACCOUNTS=true`.

El primer inicio de sesión de esta cuenta devuelve `must_change_password: true`
y el panel abre directamente la pestaña **Seguridad de la cuenta**. Hasta
guardar una clave nueva, la API bloquea los endpoints administrativos. La
contraseña nueva se comprueba con la política general (15 caracteres como
mínimo, no común ni predecible); el cambio queda auditado, limpia la marca
obligatoria e invalida las sesiones activas. Luego se inicia sesión con la
nueva clave. La pestaña también está disponible para que cualquier ADMIN
cambie su contraseña cuando lo necesite. Si olvidas la contraseña actual, este
flujo no es recuperación por correo: un operador debe restablecerla por un
proceso administrativo seguro.

La opción `--run-postman` utiliza Newman con la colección
`postman/UTA_Sumo_E2E.postman_collection.json`; el archivo temporal de variables
con contraseñas se elimina al terminar. Si las cuentas ya existen, no se pueden recuperar sus claves: usa `--rotate-existing --run-postman` para rotarlas y ejecutar Newman. Las claves aleatorias solo se muestran al crearlas
y nunca se guardan en SQL o en los scripts. No hay cuentas
privilegiadas con contraseñas por defecto compartidas.
El flujo de prueba queda asociado al evento oficial `UTA SUMO ROBOTICS CUP 2026`.

Las migraciones 06 a 20 se aplicaron en la instancia local. Se preservaron las cuentas y se cifraron sus datos personales; las filas históricas sin propietario no se exponen a participantes. Las migraciones son aditivas y no eliminan datos operativos. SQL Server Express no ofrece TDE, por lo que el cifrado de aplicación no cifra páginas, log ni backups completos. Protege el volumen y los backups con cifrado del sistema/almacenamiento o usa una edición con TDE.

La migración `36_admin_password_change_required.sql` agrega la marca de cambio obligatorio sin borrar datos; `scripts/migrate.py` la aplica en el flujo habitual.

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

## Configuración, PDF y entrega de correo

La guía para el equipo frontend está en
[GUIA_FRONTEND_CORREO.md](../../docs/backend/GUIA_FRONTEND_CORREO.md); describe
los estados que debe mostrar y confirma que las credenciales SMTP son privadas
del backend.

La migración aditiva `database/scripts/14_registration_delivery.sql` conserva
los datos actuales, añade la moneda histórica a cada pago y crea la configuración
por evento, el archivo privado del recibo, el historial de configuración y el
outbox de correos. No requiere borrar ni recrear la base.

- `GET /api/v1/events/{event_id}/registration-config` devuelve datos públicos
  del formulario, métodos e instrucciones de pago, moneda, habilitación y
  tarifas vigentes por categoría.
- `GET` y `PUT /api/v1/admin/events/{event_id}/registration-config` requieren
  `ADMIN`. Las tarifas y precios por categoría se administran en
  `/api/v1/tariffs`; cada pago conserva el monto y moneda efectivos.
- `GET /api/v1/admin/events/{event_id}/registration-config/history` devuelve
  snapshots auditados y paginados de los cambios administrativos.
- `GET /api/v1/admin/registrations` ofrece paginación SQL y filtros por evento,
  estado de inscripción/pago, fechas, código, correo de la cuenta y participante
  del roster. La referencia de transferencia se busca por un HMAC indexado; los
  listados administrativos son solo para `ADMIN`.
- Crear una inscripción emite un PDF profesional de solicitud de pago, lo cifra
  en el almacenamiento privado y asocia el documento de forma transaccional.
  La respuesta incluye `receipt_url` y `email_delivery_status` (`PENDING`,
  `SENT` o `FAILED`). No es una factura fiscal ni confirma el pago.
- `GET /api/v1/registrations/{registration_id}/receipt` descarga el PDF tras
  comprobar propiedad o rol autorizado.
- El correo se registra en `EmailOutbox` dentro de la transacción. Destinatario,
  asunto y cuerpo se cifran; SMTP se intenta después del commit. Sin SMTP, queda
  `PENDING`; un fallo conserva el registro y queda `FAILED` para reintento.
- SMTP usa `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
  `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME` y `SMTP_STARTTLS`. Sin esta configuración
  no se declara que el correo haya sido enviado.
- `GET /api/v1/admin/email-outbox?page=1&limit=50` lista estado sin exponer
  destinatarios ni contenido. `POST /api/v1/admin/email-outbox/{id}/retry`
  reintenta correos pendientes/fallidos (máximo 10 intentos) y
  `POST /api/v1/admin/registrations/{id}/resend-receipt` crea un nuevo envío.

Los textos de instrucciones y los correos se cifran con `PII_ENCRYPTION_KEY`.
Pagos existentes reciben `USD` como moneda histórica de compatibilidad. Los
reportes financieros agrupan por moneda, devuelven `totals_by_currency` y
conservan `total_amount` como compatibilidad cuando solo existe una moneda.
Pruebas automatizadas cubren PDF, outbox cifrado, permisos, configuración,
auditoría y descarga; no contactan servidores SMTP reales.

## Combate actual y marcador en tiempo real

Las migraciones `19_current_combat.sql`, `20_match_team_robot.sql` y
`24_combat_public_details.sql` añaden la
selección persistida del combate actual, auditoría de selección y el robot/orden
de cada equipo en el enfrentamiento, más detalles públicos editables. Las migraciones son aditivas; las rondas,
partidos y puntuaciones existentes se conservan. Los roles `REVIEWER` ya se
migraron a `EVENT_MANAGER`, por lo que los endpoints de control aceptan
`ADMIN` y `EVENT_MANAGER`.

- `GET /api/v1/competition/combate-actual` es público y devuelve los dos robots,
  equipos, instituciones, categoría y marcador en el contrato compatible
  `robotA`/`robotB` que consume la pantalla, además de campos snake_case para
  clientes anteriores. `estado` es legible (`En combate`, `Finalizado`, etc.)
  y `estado_code` conserva el código interno. Si no hay combate seleccionado,
  devuelve placeholders y `active: false`.
- `PUT /api/v1/competition/combate-actual` requiere `ADMIN` o `EVENT_MANAGER`.
  Acepta `match_id`, `estado` con códigos internos o `En combate`/`Finalizado`,
  `robotA.puntos` y `robotB.puntos` juntos, `detalles` y `motivo`. Los puntajes son
  puntajes absolutos y la API persiste solo la diferencia como movimientos
  auditables en `ScoreEntries`. Nombres, instituciones y ganador se derivan de SQL;
  los valores de presentación enviados por el cliente no son fuente de verdad.
- `ws://127.0.0.1:8000/ws/combate-actual` es público. Envía una instantánea al
  conectar y transmite el nuevo marcador/estado después de confirmar el commit.
  Cierres y fallos de socket retiran la conexión del administrador. Cambios a
  través de los endpoints de estado/puntuación existentes también notifican a
  los clientes conectados cuando afectan el combate seleccionado.

Ejemplo de selección e inicio desde Postman (reemplaza el ID por un partido
existente de dos equipos):

```json
{
  "match_id": 12,
  "estado": "EN_VIVO"
}
```

Actualización del marcador:

```json
{
  "puntaje_a": 2,
  "puntaje_b": 1,
  "motivo": "Marcador confirmado por el juez"
}
```

El `match_id` se obtiene al crear/listar enfrentamientos. Al crear uno, envía `robot_ids` en el mismo
orden que `team_ids` si el equipo tiene varios robots aprobados; si solo tiene
uno, el backend lo asocia automáticamente. El ConnectionManager vive en el
proceso FastAPI, como pide esta especificación; en despliegues con varios
workers se requiere un broker compartido para broadcast entre procesos.

## Reglamentos por evento y categoría

Los reglamentos son documentos PDF versionados y cifrados con
`PII_ENCRYPTION_KEY` directamente en `EventRegulations.FileContent`
(`VARBINARY(MAX)`). SQL Server guarda también el evento, categoría opcional,
título, versión, vigencia, estado, SHA-256 y auditoría. Las migraciones 31 y 32
mueven los PDF históricos desde el almacenamiento cifrado local a SQL Server,
verifican tamaño y SHA-256, y retiran la columna de ruta local después del
backfill. Los archivos locales solo se eliminan después de confirmar la
transacción de contenido.

- `GET /api/v1/events/{event_id}/regulations?category_id={category_id}` es
  público y devuelve el reglamento vigente de la categoría. Si no hay uno
  específico, usa el reglamento general del evento. Acepta `page` y `limit`.
- `GET /api/v1/regulations/{regulation_id}/file` permite ver el PDF publicado
  vigente; los borradores, archivados y eventos inactivos no se descargan.
- `GET /api/v1/admin/events/{event_id}/regulations` lista versiones y estados,
  con filtros por categoría/estado y paginación SQL.
- `POST /api/v1/admin/events/{event_id}/regulations` recibe multipart con
  `file` (PDF), `title` y `category_id` (opcional; vacío significa general),
  `effective_from` y `effective_until` opcionales. El archivo queda como
  `DRAFT` hasta publicarlo.
- `PATCH /api/v1/admin/regulations/{id}` edita título y vigencia de borradores.
- `POST /api/v1/admin/regulations/{id}/publish` publica el borrador y archiva
  atómicamente la versión publicada anterior de ese mismo alcance.
- `POST /api/v1/admin/regulations/{id}/archive` retira una publicación sin
  borrar el historial. `GET /api/v1/admin/regulations/{id}/history` presenta
  cambios auditados y paginados.

La carga y la descarga usan SQL Server; no se crea ningún PDF en una carpeta
del proyecto. La validación comprueba estructura PDF, límite configurable
`MAX_REGULATION_BYTES` (20 MiB por defecto), 1–500 páginas, ausencia de
contraseña, acciones automáticas y adjuntos incrustados. El PDF del ejemplo se
puede importar en la base existente sin reiniciarla:

```powershell
.venv\Scripts\python.exe scripts\migrate.py
.venv\Scripts\python.exe scripts\import_event_regulation.py --file "C:\ruta\Reglamento_Sumo_Amateur.pdf" --event-id 1 --category-id 1 --title "Reglamento categoría Mini Sumo Amateur RC" --publish
```

`REGULATION_STORAGE_DIR` solo se consulta durante la migración para encontrar
archivos de instalaciones antiguas; las nuevas cargas se guardan en SQL Server.

El endpoint público que debe consumir el frontend es
`GET /api/v1/events/1/regulations?category_id=1`; `download_url` contiene la
ruta pública del PDF. Para administrar documentos se requiere rol `ADMIN`.

## Administración de eventos y formularios configurables

Las migraciones 33–34 añaden descripción, lugar y fechas del evento, historial
de estado, auditoría de metadatos, versiones de formulario y respuestas asociadas a la versión usada por
cada inscripción. Aplicar con el ejecutor habitual; no requiere borrar la base.
El panel ADMIN incluye Eventos para crear/editar datos, asociar categorías y
cupos, configurar preguntas y transicionar el estado. Editar un formulario
crea una versión; las inscripciones guardan la versión y las respuestas
cifradas para conservar el historial.

- `GET /api/v1/admin/events?page=1&limit=50&search=...&status=...` lista y filtra.
- `POST /api/v1/admin/events`, `GET /api/v1/admin/events/{id}` y
  `PUT /api/v1/admin/events/{id}` crean, consultan y editan metadatos.
- `POST /api/v1/admin/events/{id}/categories` crea una categoría con nombre y
  descripción propios y la asocia al evento en la misma transacción. Desde el
  panel se pueden configurar luego cupos y tarifa para esa categoría.
- `PATCH /api/v1/admin/events/{id}/status` aplica transiciones controladas
  `DRAFT → SCHEDULED → LIVE ↔ PAUSED → FINISHED`; cancelar se permite durante
  preparación o ejecución. Eventos terminales no se reabren.
- `GET /api/v1/events/{id}/form` entrega campos vigentes al participante;
  `PUT /api/v1/admin/events/{id}/form` crea nueva versión; el historial se
  consulta en `/api/v1/admin/events/{id}/form/history`.
- `POST /api/v1/registrations` acepta `custom_answers` keyed por identificador
  de campo; valida requeridos, tipo y opciones, guarda respuestas cifradas y
  referencia la versión. El detalle autorizado entrega respuestas y versión.
- `POST /api/v1/admin/users` permite a ADMIN crear ADMIN/EVENT_MANAGER con
  validación de correo, contraseña, unicidad y auditoría. La contraseña no se
  devuelve; debe entregarse por canal seguro.
- `GET /api/v1/admin/events/{id}/audit` devuelve cambios de metadatos paginados.
- El panel Eventos también lista, carga y publica reglamentos PDF con los
  endpoints descritos en la sección anterior.
