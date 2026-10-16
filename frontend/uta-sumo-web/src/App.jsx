import { Routes, Route, Link } from 'react-router-dom';
import "./App.css";
import Bienvenida from './components/Bienvenida';
import LoginAdmin from './ModuloAdministracion/LoginAdmin';
import Inscripcion from './ModuloIncripcion/components/Inscripcion';
import fiseibotAvatar from './assets/fiseibot-avatar.png';

export default function App() {
  return (
    <>
      {/* NAVBAR GLOBAL FISEIBOT */}
      <header className="navbar-top">
        <div className="navbar-brand">
          <Link to="/" className="brand-link">
            <img src={fiseibotAvatar} alt="Fiseibot Logo" className="brand-robot-img" />
            <span className="brand-text">Fiseibot</span>
          </Link>
        </div>
        <nav className="navbar-nav">
          <Link to="/" className="nav-link">
            Inicio
          </Link>
          <Link to="/inscripcion" className="nav-link">
            Inscripción
          </Link>
          <Link to="/admin" className="btn-panel">
            Panel de revisión
          </Link>
        </nav>
      </header>

      {/* RUTAS PRINCIPALES: BIENVENIDA EN "/" */}
      <Routes>
        <Route path="/" element={<Bienvenida />} />
        <Route path="/inscripcion" element={<Inscripcion />} />
        <Route path="/admin" element={<LoginAdmin />} />
      </Routes>
    </>
  );
}
