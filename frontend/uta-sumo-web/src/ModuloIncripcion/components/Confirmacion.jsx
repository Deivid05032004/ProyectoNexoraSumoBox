function Confirmacion({ codigo, equipo, robot, tarifa, onNuevaInscripcion }) {
  return (
    <section className="registration-section">
      <div className="registration-card confirmation-card">
        <span className="success-icon" aria-hidden="true">✓</span>

        <span className="eyebrow">INSCRIPCIÓN RECIBIDA</span>
        <h2>¡Inscripción registrada con éxito!</h2>

        <p>
          Recibimos los datos de tu equipo y el comprobante será revisado por
          tesorería.
        </p>

        <div className="confirmation-summary">
          <p><strong>Equipo:</strong> {equipo}</p>
          <p><strong>Robot:</strong> {robot}</p>
          <p><strong>Valor registrado:</strong> ${tarifa}.00</p>
          {codigo && <p><strong>Código:</strong> {codigo}</p>}
        </div>

        <button className="primary-button" onClick={onNuevaInscripcion}>
          Registrar otro robot <span aria-hidden="true">→</span>
        </button>
      </div>
    </section>
  )
}

export default Confirmacion