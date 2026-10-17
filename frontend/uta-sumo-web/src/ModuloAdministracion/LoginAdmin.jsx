import { useState } from 'react';
import './LoginAdmin.css';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const PRIVILEGED_ROLES = new Set(['ADMIN', 'REVIEWER', 'TREASURY']);

export default function LoginAdmin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState({ text: '', success: false });
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault(); setBusy(true); setMessage({ text: '', success: false });
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Acceso rechazado (${response.status}).`);
      if (!PRIVILEGED_ROLES.has(body.user?.role)) {
        throw new Error('Este portal es solo para ADMIN, REVIEWER y TREASURY. Usa el acceso de participantes.');
      }
      sessionStorage.setItem('uta.access_token', body.access_token);
      sessionStorage.setItem('uta.user', JSON.stringify(body.user));
      setPassword('');
      setMessage({ text: `Sesión iniciada: ${body.user.role}. El panel administrativo se conectará con esta sesión.`, success: true });
    } catch (reason) {
      setMessage({ text: reason.message || 'No se pudo iniciar sesión.', success: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-admin-container">
      <div className="login-admin-card">
        <p className="admin-eyebrow">UTA SUMO ROBOTICS CUP</p>
        <h1 className="login-admin-title">Personal autorizado</h1>
        <p className="admin-login-description">Administradores, revisores y tesorería ingresan con las credenciales asignadas por el operador.</p>
        <form className="login-admin-form" onSubmit={handleSubmit}>
          <div className="login-form-group">
            <label htmlFor="admin-email" className="login-form-label">Correo electrónico</label>
            <input id="admin-email" type="email" className="login-form-input" value={email}
              onChange={(event) => setEmail(event.target.value)} placeholder="nombre@institucion.edu"
              required maxLength={254} autoComplete="username" />
          </div>
          <div className="login-form-group">
            <label htmlFor="admin-password" className="login-form-label">Contraseña</label>
            <input id="admin-password" type="password" className="login-form-input" value={password}
              onChange={(event) => setPassword(event.target.value)} placeholder="Contraseña asignada"
              required autoComplete="current-password" />
          </div>
          {message.text && <p className={`admin-login-message${message.success ? ' admin-login-success' : ''}`} role={message.success ? 'status' : 'alert'}>{message.text}</p>}
          <button type="submit" className="login-admin-submit-btn" disabled={busy}>
            {busy ? 'Validando...' : 'Ingresar'}
          </button>
        </form>
        <p className="login-admin-footer">Las cuentas privilegiadas se crean manualmente por un operador y no utilizan el acceso con Google.</p>
      </div>
    </div>
  );
}
