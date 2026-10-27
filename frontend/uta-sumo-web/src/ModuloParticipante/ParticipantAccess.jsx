import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import './ParticipantAccess.css';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const GOOGLE_SCRIPT = 'https://accounts.google.com/gsi/client';
let initializedGoogleClientId = '';
let googleCredentialHandler = null;

async function responseMessage(response) {
  const body = await response.json().catch(() => ({}));
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join(' ');
  return response.ok ? '' : `No se pudo completar la solicitud (${response.status}).`;
}

export default function ParticipantAccess({ initialMode = 'login' }) {
  const navigate = useNavigate();
  const location = useLocation();
  const isRegister = initialMode === 'register';
  const [institutions, setInstitutions] = useState([]);
  const [institutionId, setInstitutionId] = useState('');
  const [institutionsLoaded, setInstitutionsLoaded] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [googleReady, setGoogleReady] = useState(Boolean(window.google?.accounts?.id));
  const googleButton = useRef(null);

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/api/v1/institutions?limit=100`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseMessage(response));
        return response.json();
      })
      .then((items) => {
        if (active) {
          setInstitutions(items);
          if (items.length) setInstitutionId(String(items[0].id));
        }
      })
      .catch((reason) => active && setError(`No se pudo cargar instituciones. ${reason.message}`))
      .finally(() => active && setInstitutionsLoaded(true));

    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (window.google?.accounts?.id) {
      setGoogleReady(true);
      return undefined;
    }
    let script = document.querySelector(`script[src="${GOOGLE_SCRIPT}"]`);
    const onLoad = () => setGoogleReady(true);
    if (!script) {
      script = document.createElement('script');
      script.src = GOOGLE_SCRIPT;
      script.async = true;
      script.defer = true;
      script.onload = onLoad;
      script.onerror = () => setError('No se pudo cargar el inicio de sesión de Google.');
      document.head.appendChild(script);
    } else {
      script.addEventListener('load', onLoad);
    }
    return () => script?.removeEventListener('load', onLoad);
  }, []);

  useEffect(() => {
    if (!googleReady || !GOOGLE_CLIENT_ID || !googleButton.current) return;
    if (initializedGoogleClientId !== GOOGLE_CLIENT_ID) {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: ({ credential }) => googleCredentialHandler?.(credential),
        auto_select: false,
        cancel_on_tap_outside: true,
      });
      initializedGoogleClientId = GOOGLE_CLIENT_ID;
    }
    googleButton.current.replaceChildren();
    window.google.accounts.id.renderButton(googleButton.current, {
      theme: 'outline', size: 'large', text: 'continue_with', shape: 'rectangular',
      width: Math.min(360, googleButton.current.clientWidth || 320),
    });
  }, [googleReady, institutions.length]);

  async function saveSession(response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(await responseMessageFromBody(response, body));
    if (body.user?.role !== 'PARTICIPANT') {
      throw new Error('Este acceso es exclusivo para cuentas de participantes.');
    }
    sessionStorage.setItem('uta.access_token', body.access_token);
    sessionStorage.setItem('uta.user', JSON.stringify(body.user));
    window.dispatchEvent(new Event('uta-session-changed'));
    setNotice(`Sesión iniciada para ${body.user.email}. Ya puedes gestionar tu participación.`);
    setError('');
    const destino = location.state?.from === '/inscripcion' ? '/inscripcion' : '/participante/panel';
    navigate(destino, { replace: true });
  }

  async function responseMessageFromBody(response, body) {
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join(' ');
    return `No se pudo completar la solicitud (${response.status}).`;
  }

  async function signInWithGoogle(idToken) {
    if (busy) return;
    if (!institutionId) {
      setError('Selecciona tu institución para continuar.');
      return;
    }
    setBusy(true); setError(''); setNotice('');
    try {
      const payload = { id_token: idToken };
      if (institutionId) payload.institution_id = Number(institutionId);
      await saveSession(await fetch(`${API_BASE}/api/v1/auth/google`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      }));
    } catch (reason) {
      const message = reason.message || 'No se pudo continuar con Google.';
      setError(message.startsWith('Ya existe una cuenta con ese correo')
        ? 'Este correo ya está asociado a una cuenta creada anteriormente. Por seguridad, Google no la vincula automáticamente. Contacta al equipo organizador para revisar esa cuenta.'
        : message);
    } finally {
      setBusy(false);
    }
  }

  googleCredentialHandler = signInWithGoogle;
  return (
    <section className="participant-access" aria-labelledby="participant-access-title">
      <div className="participant-access-card">
        <p className="participant-eyebrow">UTA SUMO ROBOTICS CUP</p>
        <h1 id="participant-access-title">{isRegister ? 'Crea tu cuenta de participante' : 'Acceso de participantes'}</h1>
        <p className="participant-description">
          {isRegister
            ? 'Usa tu cuenta Google para crear tu perfil de participante. No necesitas inventar ni recordar otra contraseña.'
            : 'Continúa con la misma cuenta Google. Si es tu primera vez, crearemos tu perfil de participante automáticamente.'}
        </p>

        <div className="participant-google-profile">
          <span className="participant-google-step">{isRegister ? 'Antes de continuar' : 'Tu perfil'}</span>
          <label htmlFor="participant-institution">Institución</label>
          <select id="participant-institution" value={institutionId}
            onChange={(event) => setInstitutionId(event.target.value)} disabled={!institutions.length}>
            {!institutions.length && <option value="">{institutionsLoaded ? 'No hay instituciones disponibles' : 'Cargando instituciones…'}</option>}
            {institutions.map((institution) => (
              <option key={institution.id} value={institution.id}>{institution.name}</option>
            ))}
          </select>
          <small>Necesitamos este dato para crear tu perfil. Si tu cuenta ya existe, elegir otra institución aquí no modificará tus datos.</small>
        </div>

        {GOOGLE_CLIENT_ID ? (
          institutions.length ? <div className="google-signin-area">
            <div ref={googleButton} className="google-signin-button" />
            {!googleReady && <p className="participant-help">Cargando Google Identity Services...</p>}
          </div> : <div className="google-config-note" role="status">
            {error || (institutionsLoaded
              ? 'No hay instituciones activas para crear el perfil. Contacta al equipo organizador.'
              : 'Cargando las instituciones necesarias para crear tu perfil…')}
          </div>
        ) : (
          <div className="google-config-note" role="status">
            El acceso con Google estará disponible cuando se configure el Client ID de la aplicación.
          </div>
        )}

        <div className="participant-form">
          <p className="participant-google-security">Google confirma tu identidad y correo. La primera vez se crea tu cuenta; después, el mismo botón te da acceso. Nunca recibimos tu contraseña de Google.</p>
          {error && <p className="participant-message participant-error" role="alert">{error}</p>}
          {notice && <p className="participant-message participant-success" role="status">{notice}</p>}
          {busy && <p className="participant-help" role="status">Validando tu cuenta con Google…</p>}
        </div>
        <p className="participant-existing-account">¿Ya tienes una cuenta? Usa el mismo botón: Google abrirá tu perfil. Si es tu primera vez, se creará automáticamente.</p>
        <p className="participant-privileged-note">¿Eres administrador, revisor o tesorería? <Link to="/admin">Ingresa aquí con tu cuenta institucional.</Link></p>
      </div>
    </section>
  );
}
