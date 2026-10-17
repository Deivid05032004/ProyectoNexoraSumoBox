import { Link, Route, Routes } from 'react-router-dom';
import './App.css';
import Bienvenida from './components/Bienvenida';
import LoginAdmin from './ModuloAdministracion/LoginAdmin';
import Inscripcion from './ModuloIncripcion/components/Inscripcion';
import ParticipantAccess from './ModuloParticipante/ParticipantAccess';
import fiseibotAvatar from './assets/fiseibot-avatar.png';

export default function App() {
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
          <Link to="/inscripcion" className="nav-link">Inscripción</Link>
          <Link to="/registro" className="nav-link">Crear cuenta</Link>
          <Link to="/participante" className="nav-link">Participantes</Link>
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
          <Route path="*" element={<Bienvenida />} />
        </Routes>
      </div>
    </div>
  );
}
