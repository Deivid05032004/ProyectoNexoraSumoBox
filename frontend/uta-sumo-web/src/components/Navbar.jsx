import { Link } from 'react-router-dom';

export default function Navbar() {
  return (
    <header className="navbar">
      <div className="navbar-logo">
        <h2>Eventix</h2>
      </div>
      <nav className="navbar-links">
        <Link to="/inscripcion" className="btn-link">Inscripción</Link>
        <Link to="/administracion" className="btn-admin">Panel de revisión</Link>
      </nav>
    </header>
  );
}
