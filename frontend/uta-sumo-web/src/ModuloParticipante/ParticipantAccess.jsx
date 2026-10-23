import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import './ParticipantAccess.css';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const GOOGLE_SCRIPT = 'https://accounts.google.com/gsi/client';

async function responseMessage(response) {
  const body = await response.json().catch(() => ({}));
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join(' ');
  return response.ok ? '' : `No se pudo completar la solicitud (${response.status}).`;
}

export default function ParticipantAccess({ initialMode = 'login' }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState(initialMode);
  const [institutions, setInstitutions] = useState([]);
  const [institutionId, setInstitutionId] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [googleReady, setGoogleReady] = useState(Boolean(window.google?.accounts?.id));
  const googleButton = useRef(null);

  useEffect(() => setMode(initialMode), [initialMode]);

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
      .catch((reason) => active && setError(`No se pudo cargar instituciones. ${reason.message}`));
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
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: ({ credential }) => signInWithGoogle(credential),
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    googleButton.current.replaceChildren();
    window.google.accounts.id.renderButton(googleButton.current, {
      theme: 'outline', size: 'large', text: 'continue_with', shape: 'rectangular',
      width: Math.min(360, googleButton.current.clientWidth || 320),
    });
  }, [googleReady, institutionId, mode]);

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
    setPassword('');
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
    setBusy(true); setError(''); setNotice('');
    try {
      const payload = { id_token: idToken };
      if (institutionId) payload.institution_id = Number(institutionId);
      await saveSession(await fetch(`${API_BASE}/api/v1/auth/google`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      }));
    } catch (reason) {
      setError(reason.message || 'No se pudo iniciar sesión con Google.');
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault(); setError(''); setNotice('');
    if (mode === 'register' && password !== confirmPassword) {
      setError('Las contraseñas no coinciden.'); return;
    }
    setBusy(true);
    try {
      const payload = mode === 'register'
        ? { email, password, first_name: firstName, last_name: lastName,
            institution_id: Number(institutionId), mobile_phone: phone || null }
        : { email, password };
      const endpoint = mode === 'register' ? '/api/v1/auth/register' : '/api/v1/auth/login';
      await saveSession(await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      }));
    } catch (reason) {
      setError(reason.message || 'No se pudo completar la solicitud.');
    } finally {
      setBusy(false);
    }
  }

  const isRegister = mode === 'register';
  return (
    <section className="participant-access" aria-labelledby="participant-access-title">
      <div className="participant-access-card">
        <p className="participant-eyebrow">UTA SUMO ROBOTICS CUP</p>
        <h1 id="participant-access-title">{isRegister ? 'Crea tu cuenta de participante' : 'Acceso de participantes'}</h1>
        <p className="participant-description">
          {isRegister
            ? 'Regístrate con tu correo o continúa con Google. Las cuentas privilegiadas se administran por separado.'
            : 'Inicia sesión con correo y contraseña o con tu cuenta Google.'}
        </p>

        {GOOGLE_CLIENT_ID ? (
          <div className="google-signin-area">
            <div ref={googleButton} className="google-signin-button" />
            {!googleReady && <p className="participant-help">Cargando Google Identity Services...</p>}
          </div>
        ) : (
          <div className="google-config-note" role="status">
            El acceso con Google estará disponible cuando se configure el Client ID de la aplicación.
          </div>
        )}

        <div className="participant-divider"><span>o usa tu correo</span></div>
        <form className="participant-form" onSubmit={handleSubmit}>
          {isRegister && <>
            <div className="participant-name-row">
              <label>Nombre
                <input value={firstName} onChange={(e) => setFirstName(e.target.value)} required maxLength={100} autoComplete="given-name" />
              </label>
              <label>Apellido
                <input value={lastName} onChange={(e) => setLastName(e.target.value)} required maxLength={100} autoComplete="family-name" />
              </label>
            </div>
            <label>Institución
              <select value={institutionId} onChange={(e) => setInstitutionId(e.target.value)} required disabled={!institutions.length}>
                {institutions.map((institution) => <option key={institution.id} value={institution.id}>{institution.name}</option>)}
              </select>
            </label>
            <label>Teléfono (opcional)
              <input value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={25} autoComplete="tel" />
            </label>
          </>}
          <label>Correo electrónico
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={254} autoComplete="email" />
          </label>
          <label>Contraseña
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={isRegister ? 15 : 1} maxLength={128} autoComplete={isRegister ? 'new-password' : 'current-password'} />
            {isRegister && <small>Usa al menos 15 caracteres. No incluyas tu correo.</small>}
          </label>
          {isRegister && <label>Confirma la contraseña
            <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required minLength={15} maxLength={128} autoComplete="new-password" />
          </label>}
          {error && <p className="participant-message participant-error" role="alert">{error}</p>}
          {notice && <p className="participant-message participant-success" role="status">{notice}</p>}
          <button className="participant-submit" type="submit" disabled={busy || (isRegister && !institutions.length)}>
            {busy ? 'Procesando...' : isRegister ? 'Crear cuenta de participante' : 'Iniciar sesión'}
          </button>
        </form>
        <button className="participant-mode-toggle" type="button" onClick={() => { setMode(isRegister ? 'login' : 'register'); setError(''); setNotice(''); }}>
          {isRegister ? '¿Ya tienes cuenta? Inicia sesión' : '¿Aún no tienes cuenta? Regístrate'}
        </button>
        <p className="participant-privileged-note">¿Eres administrador, revisor o tesorería? <a href="/admin">Ingresa aquí con tu cuenta institucional.</a></p>
      </div>
    </section>
  );
}
