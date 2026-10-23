import './BienvenidaParticipante.css'

const ACCESOS = [
  { id: 'ordenes', title: 'Mis órdenes', description: 'Consulta pagos, comprobantes y estado de revisión.', icon: '01' },
  { id: 'categorias', title: 'Categorías', description: 'Revisa las categorías disponibles y sus condiciones.', icon: '02' },
  { id: 'reglamento', title: 'Reglamento oficial', description: 'Lee las reglas antes de preparar tu robot.', icon: '03' },
  { id: 'equipo', title: 'Mi equipo', description: 'Conoce los datos que debes reunir para inscribirte.', icon: '04' },
]

export default function BienvenidaParticipante({ user, onNavigate }) {
  const nombre = user?.first_name?.trim() || 'participante'

  return (
    <section className="participant-welcome" aria-labelledby="participant-welcome-title">
      <div className="participant-welcome-hero">
        <div className="participant-welcome-copy">
          <span className="participant-welcome-kicker">UTA SUMO ROBOTICS CUP</span>
          <h2 id="participant-welcome-title">¡Bienvenido, {nombre}!</h2>
          <p>Este es tu espacio para organizar la participación de tu equipo, preparar la inscripción y dar seguimiento a tus órdenes.</p>
          <button className="participant-welcome-cta" type="button" onClick={() => onNavigate('inscripcion')}>
            Inscribir mi Robot
            <span aria-hidden="true">→</span>
          </button>
        </div>
        <div className="participant-welcome-mark" aria-hidden="true">
          <span>SUMO</span>
          <strong>UTA</strong>
          <small>ROBOTICS CUP</small>
        </div>
      </div>

      <div className="participant-welcome-section-heading">
        <div>
          <span className="participant-welcome-kicker">TU PANEL</span>
          <h3>¿Qué necesitas hacer?</h3>
        </div>
        <p>Accede rápidamente a la información de tu participación.</p>
      </div>

      <div className="participant-welcome-links">
        {ACCESOS.map((acceso) => (
          <button
            className="participant-welcome-link"
            key={acceso.id}
            type="button"
            onClick={() => onNavigate(acceso.id)}
          >
            <span className="participant-welcome-link-number">{acceso.icon}</span>
            <span className="participant-welcome-link-text">
              <strong>{acceso.title}</strong>
              <small>{acceso.description}</small>
            </span>
            <span className="participant-welcome-link-arrow" aria-hidden="true">↗</span>
          </button>
        ))}
      </div>
    </section>
  )
}
