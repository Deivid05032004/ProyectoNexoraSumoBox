import { Route, Routes, Link } from 'react-router-dom';
import './App.css';
import LoginAdmin from './ModuloAdministracion/LoginAdmin';
import ParticipantAccess from './ModuloParticipante/ParticipantAccess';

export default function App() {
  return (
    <div className="app-layout">
      <header className="navbar-top">
        <div className="navbar-brand"><Link to="/">UTA SUMO</Link></div>
        <nav className="navbar-nav" aria-label="Navegación principal">
          <Link to="/inscripcion" className="nav-link">Inscripción</Link>
          <Link to="/participante" className="nav-link">Participantes</Link>
          <Link to="/admin" className="btn-panel">Personal autorizado</Link>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<ParticipantAccess initialMode="register" />} />
          <Route path="/inscripcion" element={<ParticipantAccess initialMode="register" />} />
          <Route path="/participante" element={<ParticipantAccess initialMode="login" />} />
          <Route path="/admin" element={<LoginAdmin />} />
          <Route path="*" element={<ParticipantAccess initialMode="login" />} />
        </Routes>
      </main>
    </div>
  );
}
