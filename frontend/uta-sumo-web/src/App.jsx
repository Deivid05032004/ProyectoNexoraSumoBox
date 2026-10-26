import { useEffect, useState } from 'react';
import { Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import './App.css';
import Bienvenida from './components/Bienvenida';
import LoginAdmin from './ModuloAdministracion/LoginAdmin';
import AdminDashboard from './ModuloAdministracion/AdminDashboard';
import Resultados from './ModuloResultados/Resultados';
import Inscripcion from './ModuloIncripcion/components/Inscripcion';
import ParticipantAccess from './ModuloParticipante/ParticipantAccess';
import PanelParticipante from './ModuloIncripcion/components/PanelParticipante';
import fiseibotAvatar from './assets/fiseibot-avatar.png';

function leerUsuarioSesion() {
  try {
    return JSON.parse(sessionStorage.getItem('uta.user') || 'null');
  } catch {
    return null;
  }
}

export default function App() {
  const navigate = useNavigate();
  const [, setUser] = useState(leerUsuarioSesion);
  const user = leerUsuarioSesion();

  useEffect(() => {
    const actualizarSesion = () => {
      setUser(leerUsuarioSesion());
    };
    window.addEventListener('uta-session-changed', actualizarSesion);
    window.addEventListener('storage', actualizarSesion);
    return () => {
      window.removeEventListener('uta-session-changed', actualizarSesion);
      window.removeEventListener('storage', actualizarSesion);
    };
  }, []);

  function cerrarSesionParticipante() {
    sessionStorage.removeItem('uta.access_token');
    sessionStorage.removeItem('uta.user');
    window.dispatchEvent(new Event('uta-session-changed'));
    navigate('/participante', { replace: true });
  }

  const participanteActivo = user?.role === 'PARTICIPANT';
  const adminActivo = ['ADMIN', 'EVENT_MANAGER'].includes(user?.role);

  return (
    <div className="app-layout">
      <header className="navbar-top">
        <div className="navbar-brand">
          <Link to="/" className="brand-link">
            <img src={fiseibotAvatar} alt="Fiseibot Logo" className="brand-robot-img" />
            <span className="brand-text">Fiseibot</span>
          </Link>
        </div>
        <nav className="navbar-nav" aria-label="Navegación principal">
          {!participanteActivo && <Link to="/" className="nav-link">Inicio</Link>}
          <Link to="/resultados" className="nav-link">Ver resultados</Link>
          <Link to={participanteActivo ? '/participante/panel' : '/participante'} className="nav-link">Participantes</Link>
          {participanteActivo ? (
            <>
              <Link to="/inscripcion" className="nav-link nav-link-hidden">Mi inscripción</Link>
              <button type="button" className="nav-logout" onClick={cerrarSesionParticipante}>
                Cerrar sesión
              </button>
            </>
          ) : (
            <>
              <Link to="/inscripcion" className="nav-link nav-link-hidden">Inscripción</Link>
              <Link to="/registro" className="nav-link nav-link-hidden">Crear cuenta</Link>
            </>
          )}
          {!participanteActivo && (
            <Link to={adminActivo ? "/admin/dashboard" : "/admin"} className="btn-panel">
              {adminActivo ? "Panel de administración" : "Personal autorizado"}
            </Link>
          )}
        </nav>
      </header>
      <div className="app-main">
        <Routes>
          <Route path="/" element={<Bienvenida />} />
          <Route path="/resultados" element={<Resultados />} />
          <Route path="/inscripcion" element={<Inscripcion />} />
          <Route path="/registro" element={<ParticipantAccess initialMode="register" />} />
          <Route path="/participante" element={participanteActivo
            ? <Navigate to="/participante/panel" replace />
            : <ParticipantAccess initialMode="login" />} />
          <Route path="/participante/panel" element={participanteActivo
            ? <PanelParticipante user={user} />
            : <Navigate to="/participante" replace />} />
          <Route path="/admin" element={participanteActivo
            ? <Navigate to="/participante/panel" replace />
            : <LoginAdmin />} />
          <Route path="/admin/dashboard" element={adminActivo
            ? <AdminDashboard />
            : participanteActivo ? <Navigate to="/participante/panel" replace /> : <Navigate to="/admin" replace />} />
          <Route path="/admin/panel" element={adminActivo
            ? <AdminDashboard />
            : participanteActivo ? <Navigate to="/participante/panel" replace /> : <Navigate to="/admin" replace />} />
          <Route path="*" element={<Bienvenida />} />
        </Routes>
      </div>
    </div>
  );
}
