import { Routes, Route, Link } from 'react-router-dom';
import "./App.css";
import LoginAdmin from './ModuloAdministracion/LoginAdmin';

export default function App() {
  return (
    <>
      {/* TU DISEÑO INTACTO */}
      <header className="navbar-top">
        <div className="navbar-brand">
          <Link to="/">Eventix</Link>
        </div>
        <nav className="navbar-nav">
          <Link to="/inscripcion" className="nav-link">
            Inscripción
          </Link>
          <Link to="/admin" className="btn-panel">
            Panel de revisión
          </Link>
        </nav>
      </header>

      {/* LA RUTA QUE CONECTA EL BOTÓN CON TU LOGIN */}
      <Routes>
        <Route path="/admin" element={<LoginAdmin />} />
      </Routes>
    </>
  );
}