# Integración del correo con el frontend

El envío de correo pertenece al backend. El frontend solo llama las rutas
habituales de inscripción y pagos, y muestra al participante el resultado de
`email_delivery_status` o `notification_status`. No debe conectarse al servidor
SMTP ni pedir o guardar contraseñas del correo.

## Configuración privada del backend

El SMTP está configurado en `backend/uta_sumo_api/.env` en el entorno local y
el envío de prueba fue aceptado por el servidor SMTP. Para desplegar el backend,
define estas variables en el gestor de secretos o entorno privado del servidor:

```dotenv
SMTP_HOST=<servidor SMTP del proveedor>
SMTP_PORT=587
SMTP_USERNAME=<cuenta autorizada para enviar>
SMTP_PASSWORD=<contraseña de aplicación o credencial SMTP>
SMTP_FROM_EMAIL=<dirección remitente verificada>
SMTP_FROM_NAME=UTA SUMO ROBOTICS CUP
SMTP_STARTTLS=true
```

`SMTP_PASSWORD` es la variable que contiene la clave SMTP. Su valor es secreto:
se configura solamente en el `.env` local ignorado por Git o en el gestor de
secretos del servidor. No se copia a `.env` del frontend, JavaScript, Postman,
commits ni mensajes. El proveedor puede requerir una contraseña de aplicación
o credencial SMTP específica; no se debe asumir que es la contraseña normal
de la cuenta. Reinicia el proceso backend después de cambiar la configuración.

## Flujo que consume el frontend

1. El participante crea su inscripción con `POST /api/v1/registrations`.
   La respuesta incluye `email_delivery_status` y el `receipt_url` privado.
2. El participante obtiene sus pagos con `GET /api/v1/payments/my` y carga el
   comprobante con `POST /api/v1/payments/{payment_id}/receipt` como `multipart/form-data`.
   La respuesta incluye `notification_status`.
3. Un administrador revisa el pago con `POST /api/v1/payments/{payment_id}/review`.
   La respuesta incluye `notification_status`.
4. El participante consulta el estado del pago/inscripción en las rutas `GET`
   existentes. El correo avisa del resultado; no sustituye la consulta del
   estado real en la API.

Las rutas protegidas requieren `Authorization: Bearer <access_token>`. La carga
del comprobante requiere rol `PARTICIPANT`; la revisión requiere `ADMIN`.
El PDF de solicitud se descarga usando `GET /api/v1/registrations/{registration_id}/receipt`
con el token del participante propietario o de un administrador. Nunca se
expone una ruta de almacenamiento local.

## Cómo presentar los estados

| Estado API | Mensaje recomendado |
| --- | --- |
| `SENT` | “Enviamos la notificación al correo de tu cuenta.” |
| `PENDING` | “La operación quedó guardada; el correo está pendiente de envío. Consulta el estado en Mis pagos.” |
| `FAILED` | “La operación quedó guardada, pero no se pudo enviar el correo. El equipo puede reintentar el envío.” |

No se debe revertir una inscripción, carga de comprobante o revisión cuando el
correo falla: los datos operativos ya se guardaron y el estado del correo es
independiente. No afirmar que llegó a la bandeja de entrada; `SENT` indica que
el servidor SMTP aceptó el mensaje. El receptor podría verlo en Spam o tener
reglas adicionales.

## Reintentos administrativos

Un administrador puede consultar `GET /api/v1/admin/email-outbox?status=FAILED`
o `?status=PENDING`, y reintentar con
`POST /api/v1/admin/email-outbox/{outbox_id}/retry`. El límite es de 10 intentos.
Para reenviar las instrucciones/PDF de una inscripción se usa
`POST /api/v1/admin/registrations/{registration_id}/resend-receipt`. Estas rutas
son solo para uso administrativo; no se deben llamar desde una cuenta de
participante.

La tabla `EmailOutbox` conserva el resultado sin exponer destinatario, asunto ni
cuerpo en sus listados administrativos. El sistema adjunta el PDF de solicitud
de pago al correo de inscripción; no es factura fiscal ni confirmación de pago.
El comprobante bancario que carga el participante no se adjunta ni reenvía por
correo.

## Antes de producción

- Configurar los siete valores SMTP anteriores en el backend de producción y
  reiniciarlo.
- Configurar la dirección remitente y dominio con SPF/DKIM/DMARC en el proveedor
  de correo para mejorar autenticación y entregabilidad.
- Comprobar un destinatario real, revisar el estado `SENT` en la respuesta y
  verificar bandeja de entrada y Spam.
- Vigilar el outbox y reintentar fallos desde una sesión administrativa.

La prueba local confirmó la aceptación SMTP de un correo de prueba con PDF.
No confirma la autenticación DNS del dominio de producción ni la entrega final
en la bandeja del destinatario.
