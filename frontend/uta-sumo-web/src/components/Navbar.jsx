import { Link } from 'react-router-dom';

export default function Navbar() {
  return (
    <header className="navbar">
      <div className="navbar-logo">
        <h2>Fiseibot</h2>
      </div>
      <nav className="navbar-links">
        <Link to="/" className="btn-link">Inicio</Link>
        <Link to="/resultados" className="btn-link">Ver resultados</Link>
        <Link to="/inscripcion" className="btn-link">Inscripción</Link>
        <Link to="/admin" className="btn-admin">Panel de revisión</Link>
      </nav>
    </header>
  );
}
