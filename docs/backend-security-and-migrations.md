# Seguridad, datos y migraciones del backend

## Clasificación y controles

| Grupo | Tratamiento | Acceso |
| --- | --- | --- |
| Credenciales | Contraseñas con Argon2id; bcrypt solo se acepta para migrar hashes heredados. El email se cifra con AES-GCM y se busca mediante HMAC. | La persona inicia sesión con email; ADMIN gestiona roles y estado. |
| Datos personales | Nombres, teléfonos, email y texto libre cifrados con AES-GCM a nivel de aplicación. | El propietario, ADMIN y rutas de revisión según rol; teléfonos se ocultan a REVIEWER. |
| Comprobantes | Archivos cifrados con AES-GCM en almacenamiento privado; metadatos y versión de cifrado en SQL. | Propietario, ADMIN y TREASURY. Descarga con autorización y sin caché. |
| Operación | Importes, estados, eventos, categorías e identificadores quedan consultables para mantener integridad, filtros y reportes. | Control por endpoint y rol. |
| Auditoría | Acciones de seguridad, actor y objetivo referenciados por ID; no registra contraseñas, tokens ni hashes. | Solo ADMIN. |

- El registro y su perfil se guardan en una transacción. Inscripción,
  participantes, pago inicial e historial también se escriben atómicamente.
- Las transiciones de pago/inscripción se validan en el servidor y se guardan
  con historial. Cada cuenta tiene aislamiento por propietario.
- El cambio de contraseña incrementa `TokenVersion` y revoca JWT anteriores.
- Los listados usan `OFFSET/FETCH` en SQL, límites de 1–100 filas y encabezados
  `X-Total-Count`, `X-Page`, `X-Page-Size`, `X-Total-Pages`. Los detalles de
  reportes también usan `COUNT_BIG` y selección paginada dentro de SQL. Los
  agregados de estado, categoría, tendencia e importes se calculan en SQL y
  devuelven solo grupos agregados.
- Comprobantes limitados por tamaño y validados por extensión, MIME y firma
  inicial; publicación del archivo temporal atómica y limpieza si falla SQL.
- Migraciones transaccionales, con checksum en `SchemaMigrations`; agregar una
  migración nueva en vez de editar una aplicada. 06 convierte los datos sensibles
  existentes, 07 finaliza email/HMAC y 08 agrega índices para filtros y páginas.

## Pendientes para un despliegue productivo

1. **Verificación de control del correo:** la API comprueba sintaxis y DNS/MX,
   pero no envía enlace de verificación. Integrar proveedor de correo, tokens de
   un solo uso y expiración antes de habilitar cuentas públicas en producción.
2. **Protección contra fuerza bruta:** no existe rate limit distribuido para
   login/registro. Configurarlo en gateway/WAF o con un mecanismo compartido
   entre réplicas.
3. **Cifrado completo de archivos SQL:** la columna de datos sensibles y los
   comprobantes sí se cifran a nivel de aplicación, pero SQL Server Express no
   dispone de TDE. Cifrar el volumen, logs y backups fuera de SQL o migrar a una
   edición que admita TDE. No se afirma que este paso de almacenamiento esté
   activado automáticamente.
4. **Gestión/rotación de claves:** mantener `SECRET_KEY` y `PII_ENCRYPTION_KEY`
   en un gestor de secretos y copias seguras. La rotación PII requiere un
   procedimiento coordinado de re-cifrado y actualización de índices HMAC.
5. **Archivos:** las comprobaciones actuales no sustituyen escaneo antimalware ni
   análisis completo de PDF/imagen. Agregar antivirus/servicio de análisis y
   retención/borrado institucional para producción.
6. **Certificados SQL:** la configuración local confía en el certificado del
   servidor; producción debe usar certificado válido y `DB_TRUST_SERVER_CERTIFICATE=no`.
7. **Operación:** automatizar backups cifrados, pruebas de restauración,
   monitoreo/alertas y política de retención. No hay exportación CSV/XLSX
   implementada; los reportes se entregan como JSON paginado.

## Migración y pruebas locales

Desde `backend/uta_sumo_api`:

```powershell
.venv\Scripts\python.exe scripts\migrate.py
$env:RUN_SQLSERVER_TESTS = '1'
.venv\Scripts\python.exe -m pytest -q
```

La migración de esquema no borra registros. `--reset-local --confirm-drop` es
una herramienta aparte para restablecimiento destructivo de la base local y no
se requiere para aplicar cambios normales. Las identidades demo solo se crean
en la instancia local y tienen claves aleatorias impresas al crearse.
