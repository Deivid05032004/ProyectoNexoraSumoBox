import { useState } from 'react'
import { subirComprobante } from '../services/inscripcionesApi'

const TIPOS_COMPROBANTE = ['image/jpeg', 'image/png', 'application/pdf']
const TAMANIO_MAXIMO_ARCHIVO = 5 * 1024 * 1024

function errorArchivo(archivo) {
  if (!archivo) return 'Adjunta el comprobante de transferencia.'
  if (!TIPOS_COMPROBANTE.includes(archivo.type)) return 'Solo se aceptan archivos JPG, PNG o PDF.'
  if (archivo.size > TAMANIO_MAXIMO_ARCHIVO) return 'El comprobante no puede superar los 5 MB.'
  return ''
}

export default function Confirmacion({ registro, token, onNuevaInscripcion }) {
  const [comprobante, setComprobante] = useState(null)
  const [referencia, setReferencia] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [enviado, setEnviado] = useState(false)
  const monto = Number(registro.amount).toFixed(2)

  async function manejarComprobante(evento) {
    evento.preventDefault()
    const errorValidacion = errorArchivo(comprobante)
    if (errorValidacion) { setError(errorValidacion); return }
    setEnviando(true); setError('')
    try {
      await subirComprobante(registro.payment_id, comprobante, token, referencia)
      setEnviado(true)
    } catch (reason) {
      setError(reason.message || 'No se pudo enviar el comprobante.')
    } finally { setEnviando(false) }
  }

  return <section className="registration-section"><div className="registration-card confirmation-card">
    <span className="success-icon" aria-hidden="true">✓</span>
    <span className="eyebrow">INSCRIPCIÓN CREADA</span>
    <h1>{enviado ? '¡Comprobante enviado a revisión!' : 'Tu orden de pago está lista'}</h1>
    <p>{enviado ? 'Tesorería revisará tu comprobante. Podrás consultar el estado desde el acceso de participantes.' : 'Completa el segundo paso adjuntando el comprobante de transferencia.'}</p>
    <div className="confirmation-summary"><p><strong>Equipo:</strong> {registro.team_name}</p><p><strong>Robot:</strong> {registro.robot_name}</p><p><strong>Valor a pagar:</strong> ${monto}</p><p><strong>Código:</strong> {registro.code}</p></div>
    {!enviado && <form className="receipt-form" onSubmit={manejarComprobante} noValidate>
      <label htmlFor="referencia">Referencia de transferencia (opcional)<input id="referencia" maxLength="150" value={referencia} onChange={(event) => setReferencia(event.target.value)} /></label>
      <label className="file-input" htmlFor="comprobante"><span>{comprobante?.name || 'Seleccionar comprobante'}</span><input id="comprobante" type="file" accept="image/jpeg,image/png,application/pdf" onChange={(event) => { const archivo = event.target.files?.[0] || null; setComprobante(archivo); setError(errorArchivo(archivo)) }} /></label>
      <p className="receipt-help">Formatos permitidos: JPG, PNG o PDF; máximo 5 MB.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="primary-button" type="submit" disabled={enviando}>{enviando ? 'Enviando comprobante...' : 'Enviar comprobante a revisión'}</button>
    </form>}
    {enviado && <button className="primary-button" onClick={onNuevaInscripcion}>Registrar otro robot <span aria-hidden="true">→</span></button>}
  </div></section>
}
