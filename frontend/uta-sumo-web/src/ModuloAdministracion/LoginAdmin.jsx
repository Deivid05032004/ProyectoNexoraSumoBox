import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiRequest, setAdminSession } from './services/adminApi';
import './LoginAdmin.css';

export default function LoginAdmin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setMessage('');
    try {
      const auth = await apiRequest('/api/v1/auth/login', {
        method: 'POST', body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!['ADMIN', 'EVENT_MANAGER'].includes(auth.user?.role)) {
        throw new Error('Esta cuenta no tiene un rol administrativo autorizado.');
      }
      setAdminSession(auth);
      navigate('/admin/dashboard', { replace: true });
    } catch (error) {
      setMessage(error.message || 'No se pudo iniciar sesión.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-admin-container">
      <div className="login-admin-card">
        <p className="admin-eyebrow">UTA SUMO ROBOTICS CUP 2026</p>
        <h1 className="login-admin-title">Acceso de Revisores</h1>
        <p className="admin-login-description">Ingreso exclusivo para personal administrativo autorizado.</p>
        <form className="login-admin-form" onSubmit={handleSubmit}>
          <div className="login-form-group">
            <label htmlFor="admin-email" className="login-form-label">Correo electrónico</label>
            <input id="admin-email" type="email" className="login-form-input" value={email}
              onChange={(event) => setEmail(event.target.value)} placeholder="nombre@institucion.edu"
              required autoComplete="username" />
          </div>
          <div className="login-form-group">
            <label htmlFor="admin-password" className="login-form-label">Contraseña</label>
            <input id="admin-password" type="password" className="login-form-input" value={password}
              onChange={(event) => setPassword(event.target.value)} required autoComplete="current-password" />
          </div>
          {message && <p className="admin-login-message" role="alert">{message}</p>}
          <button type="submit" className="login-admin-submit-btn" disabled={loading}>
            {loading ? 'Validando credenciales…' : 'Ingresar al panel'}
          </button>
        </form>
      </div>
    </div>
  );
}
