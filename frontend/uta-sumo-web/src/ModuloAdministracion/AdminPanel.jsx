import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './AdminPanel.css';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

function cerrarSesion(navigate) {
  sessionStorage.removeItem('uta.access_token');
  sessionStorage.removeItem('uta.user');
  window.dispatchEvent(new Event('uta-session-changed'));
  navigate('/admin', { replace: true });
}

export default function AdminPanel() {
  const navigate = useNavigate();
  const [usuario, setUsuario] = useState(null);
  const [resumen, setResumen] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const token = sessionStorage.getItem('uta.access_token');
    if (!token) {
      cerrarSesion(navigate);
      return;
    }

    async function cargarPanel() {
      try {
        const headers = { Authorization: `Bearer ${token}` };
        const [meResponse, dashboardResponse] = await Promise.all([
          fetch(`${API_BASE}/api/v1/auth/me`, { headers }),
          fetch(`${API_BASE}/api/v1/admin/dashboard`, { headers }),
        ]);
        const me = await meResponse.json().catch(() => ({}));
        const dashboard = await dashboardResponse.json().catch(() => ({}));

        if (meResponse.status === 401 || meResponse.status === 403 || me.role !== 'ADMIN') {
          cerrarSesion(navigate);
          return;
        }
        if (!dashboardResponse.ok) {
          throw new Error(typeof dashboard.detail === 'string' ? dashboard.detail : 'No se pudo cargar el panel administrativo.');
        }
        setUsuario(me);
        setResumen(dashboard);
      } catch (reason) {
        setError(reason.message || 'No se pudo conectar con el servidor.');
      }
    }

    cargarPanel();
  }, [navigate]);

  if (error) {
    return <section className="admin-panel"><div className="admin-panel-card"><h1>Panel administrativo</h1><p className="admin-panel-error">{error}</p><button onClick={() => cerrarSesion(navigate)}>Volver al acceso</button></div></section>;
  }

  if (!resumen || !usuario) {
    return <section className="admin-panel"><div className="admin-panel-card"><p>Verificando sesión y cargando el panel...</p></div></section>;
  }

  return <section className="admin-panel">
    <div className="admin-panel-header">
      <div><p className="admin-panel-eyebrow">UTA SUMO ROBOTICS CUP</p><h1>Panel administrativo</h1><p>Sesión: {usuario.first_name} {usuario.last_name}</p></div>
      <button className="admin-logout" onClick={() => cerrarSesion(navigate)}>Cerrar sesión</button>
    </div>
    <div className="admin-stats" aria-label="Resumen administrativo">
      <article><span>Inscripciones</span><strong>{resumen.registrations}</strong></article>
      <article><span>Pagos pendientes de revisión</span><strong>{resumen.payments_pending_review}</strong></article>
      <article><span>Usuarios activos</span><strong>{resumen.active_users}</strong></article>
    </div>
  </section>;
}
