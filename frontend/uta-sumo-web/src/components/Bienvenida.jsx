import { Link } from 'react-router-dom';
import fiseibotAvatar from '../assets/fiseibot-avatar.png';
import './Bienvenida.css';

export default function Bienvenida() {
  return (
    <div className="home-wrapper">
      <main className="home-content">
        {/* Columna Izquierda: Información y Accesos */}
        <div className="hero-text-col">
          <div className="institution-badge">
            <span className="badge-dot" />
            <span>CLUB DE ROBÓTICA FISEI · UTA</span>
          </div>

          <h1 className="hero-title">
            Torneo de Robótica <br />
            <span className="hero-title-accent">UTA Sumo Robotics Cup</span>
          </h1>

          <p className="hero-slogan">
            «Nuestra misión: ¡innovar y crear!»
          </p>

          <p className="hero-description">
            Bienvenido al portal oficial de registro y gestión de competencia para la categoría{' '}
            <strong>Mini Sumo RC Amateur</strong> de la Facultad de Ingeniería en Sistemas,
            Electrónica e Industrial de la Universidad Técnica de Ambato.
          </p>

          <div className="hero-actions">
            <Link to="/inscripcion" className="btn-primary-action">
              <span>Inscribir mi Robot</span>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </Link>

            <Link to="/admin" className="btn-secondary-action">
              <span>Panel de Revisión</span>
            </Link>
          </div>

          <div className="hero-features-list">
            <div className="feature-pill">
              <span className="feature-pill-icon">⚡</span>
              <div>
                <strong>Mini Sumo RC</strong>
                <small>Categoría Amateur</small>
              </div>
            </div>
            <div className="feature-pill">
              <span className="feature-pill-icon">⚖️</span>
              <div>
                <strong>Reglamento Oficial</strong>
                <small>Control y pesaje técnico</small>
              </div>
            </div>
            <div className="feature-pill">
              <span className="feature-pill-icon">👥</span>
              <div>
                <strong>Equipos</strong>
                <small>2 a 3 integrantes</small>
              </div>
            </div>
          </div>
        </div>

        {/* Columna Derecha: Tarjeta Institucional con el Robot */}
        <div className="hero-card-col">
          <div className="robot-showcase-card">
            <div className="card-header-badge">
              <span className="status-indicator" />
              <span>CONVOCATORIA OFICIAL</span>
            </div>

            <div className="robot-avatar-container">
              <img
                src={fiseibotAvatar}
                alt="Robot Fiseibot"
                className="fiseibot-robot-image"
              />
            </div>

            <div className="robot-card-info">
              <h2 className="card-brand-name">Fiseibot</h2>
              <span className="card-brand-sub">Club de Robótica FISEI</span>
            </div>

            <div className="card-details-grid">
              <div className="card-detail-item">
                <span className="detail-label">Competencia</span>
                <span className="detail-value">Sumo Box</span>
              </div>
              <div className="card-detail-item">
                <span className="detail-label">Sede</span>
                <span className="detail-value">Campus Huachi · UTA</span>
              </div>
              <div className="card-detail-item">
                <span className="detail-label">Modalidad</span>
                <span className="detail-value">Radiocontrol (RC)</span>
              </div>
              <div className="card-detail-item">
                <span className="detail-label">Instagram Oficial</span>
                <a
                  href="https://www.instagram.com/fiseibot/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="detail-link"
                >
                  @fiseibot ↗
                </a>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer compacto sin scroll */}
      <footer className="home-footer">
        <span>© 2026 Club de Robótica FISEI · Universidad Técnica de Ambato</span>
        <span>Facultad de Ingeniería en Sistemas, Electrónica e Industrial · Ambato, Ecuador</span>
      </footer>
    </div>
  );
}
