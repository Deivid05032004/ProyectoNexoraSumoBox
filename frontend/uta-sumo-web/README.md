# UTA SUMO frontend

Interfaz React/Vite de acceso para participantes y personal autorizado.

## Configuración local

Desde esta carpeta:

```powershell
Copy-Item .env.example .env
npm install
npm run dev
```

Configura `.env`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_GOOGLE_CLIENT_ID=
```

El Client ID debe coincidir con `GOOGLE_CLIENT_ID` en
`backend/uta_sumo_api/.env`. Autoriza `http://localhost:5173` como JavaScript
origin en Google Cloud Console. Reinicia Vite tras cambiar `.env`.

## Rutas y roles

- `/` y `/inscripcion`: registro de participante con email/contraseña o Google.
- `/participante`: login de participante con email/contraseña o Google.
- `/admin`: ingreso manual de `ADMIN`, `REVIEWER` y `TREASURY`; no incluye
  botón Google ni crea cuentas privilegiadas.

El alta de roles privilegiados se realiza manualmente desde el backend con
`scripts/provision_operator_user.py`. El frontend no permite asignar roles.
Google Identity Services autentica y entrega un ID token al endpoint backend;
la contraseña de Google nunca llega a esta aplicación. Los JWT de API se
mantienen en `sessionStorage` durante la sesión de pestaña.

El funcionamiento real de Google requiere configurar un Client ID de Google
Cloud en ambos proyectos. Sin este valor, la interfaz muestra que la función
está pendiente de configuración y los endpoints backend responden `503`.
