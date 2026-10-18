import { useEffect, useState } from 'react';
import { Link, Route, Routes, useNavigate } from 'react-router-dom';
import './App.css';
import Bienvenida from './components/Bienvenida';
import LoginAdmin from './ModuloAdministracion/LoginAdmin';
import AdminPanel from './ModuloAdministracion/AdminPanel';
import Inscripcion from './ModuloIncripcion/components/Inscripcion';
import ParticipantAccess from './ModuloParticipante/ParticipantAccess';
import fiseibotAvatar from './assets/fiseibot-avatar.png';

export default function App() {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem('uta.user') || 'null'); } catch { return null; }
  });

  useEffect(() => {
    const actualizarSesion = () => {
      try { setUser(JSON.parse(sessionStorage.getItem('uta.user') || 'null')); } catch { setUser(null); }
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
          <Link to="/" className="nav-link">Inicio</Link>
          {participanteActivo ? <>
            <Link to="/inscripcion" className="nav-link">Mi inscripción</Link>
            <button type="button" className="nav-logout" onClick={cerrarSesionParticipante}>Cerrar sesión</button>
          </> : <>
            <Link to="/inscripcion" className="nav-link">Inscripción</Link>
            <Link to="/registro" className="nav-link">Crear cuenta</Link>
            <Link to="/participante" className="nav-link">Participantes</Link>
          </>}
          <Link to="/admin" className="btn-panel">Personal autorizado</Link>
        </nav>
      </header>
      <div className="app-main">
        <Routes>
          <Route path="/" element={<Bienvenida />} />
          <Route path="/inscripcion" element={<Inscripcion />} />
          <Route path="/registro" element={<ParticipantAccess initialMode="register" />} />
          <Route path="/participante" element={<ParticipantAccess initialMode="login" />} />
          <Route path="/admin" element={<LoginAdmin />} />
          <Route path="/admin/panel" element={<AdminPanel />} />
          <Route path="*" element={<Bienvenida />} />
        </Routes>
      </div>
    </div>
  );
}
