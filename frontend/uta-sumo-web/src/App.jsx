import { Link } from 'react-router-dom';
import "./App.css";

export default function Navbar() {
  return (
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
  );
}