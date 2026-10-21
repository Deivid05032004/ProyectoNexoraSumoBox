import { useState } from 'react'
import { descargarInstruccionesPago, subirComprobante } from '../services/inscripcionesApi'

const TIPOS_COMPROBANTE = ['image/jpeg', 'image/png', 'application/pdf']
const TAMANIO_MAXIMO_ARCHIVO = 5 * 1024 * 1024

function errorArchivo(archivo) {
  if (!archivo) return 'Adjunta el comprobante de transferencia.'
  if (!TIPOS_COMPROBANTE.includes(archivo.type)) return 'Solo se aceptan archivos JPG, PNG o PDF.'
  if (archivo.size > TAMANIO_MAXIMO_ARCHIVO) return 'El comprobante no puede superar los 5 MB.'
  return ''
}

export default function Confirmacion({ registro, configuracion, token, onNuevaInscripcion, onVerOrdenes }) {
  const [comprobante, setComprobante] = useState(null)
  const [referencia, setReferencia] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [enviado, setEnviado] = useState(false)
  const [descargando, setDescargando] = useState(false)
  const monto = Number(registro.amount).toFixed(2)

  async function manejarDescarga() {
    setDescargando(true); setError('')
    try {
      await descargarInstruccionesPago(registro, token)
    } catch (reason) {
      setError(reason.message || 'No se pudieron descargar las instrucciones de pago.')
    } finally {
      setDescargando(false)
    }
  }

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
    <p>{enviado ? 'Tesorería revisará tu comprobante. Podrás consultar el estado en Mis órdenes de pago.' : 'Adjunta ahora el comprobante o vuelve después desde Mis órdenes de pago.'}</p>
    <div className="confirmation-summary">
      <p><strong>Equipo:</strong> {registro.team_name}</p>
      <p><strong>Robot:</strong> {registro.robot_name}</p>
      <p><strong>Categoría:</strong> {registro.category_name}</p>
      <p><strong>Valor a pagar:</strong> {configuracion?.currency || 'USD'} {monto}</p>
      <p><strong>Código:</strong> {registro.code}</p>
      {registro.participants?.map((participante) => (
        <p key={`${participante.position}-${participante.id}`}>
          <strong>{participante.slot === 'COACH' ? 'Coach' : `Participante ${participante.position}`}:</strong>{' '}
          {participante.first_name} {participante.last_name}
        </p>
      ))}
    </div>
    {!enviado && <>
      <div className="payment-box">
        <h2>Instrucciones de pago</h2>
        {configuracion?.payment_instructions
          ? <p className="registration-instructions">{configuracion.payment_instructions}</p>
          : <p>Descarga el documento de instrucciones de pago generado para esta inscripción.</p>}
        {configuracion?.payment_methods?.length > 0 && (
          <ul>{configuracion.payment_methods.map((metodo) => <li key={metodo}>{metodo}</li>)}</ul>
        )}
        {configuracion?.receipt_message && <p>{configuracion.receipt_message}</p>}
        <button className="secondary-button" type="button" onClick={manejarDescarga} disabled={descargando}>
          {descargando ? 'Descargando...' : 'Descargar instrucciones de pago (PDF)'}
        </button>
      </div>
    </>}
    {!enviado && <form className="receipt-form" onSubmit={manejarComprobante} noValidate>
      <label htmlFor="referencia">Referencia de transferencia (opcional)<input id="referencia" maxLength="150" value={referencia} onChange={(event) => setReferencia(event.target.value)} /></label>
      <label className="file-input" htmlFor="comprobante"><span>{comprobante?.name || 'Seleccionar comprobante'}</span><input id="comprobante" type="file" accept="image/jpeg,image/png,application/pdf" onChange={(event) => { const archivo = event.target.files?.[0] || null; setComprobante(archivo); setError(errorArchivo(archivo)) }} /></label>
      <p className="receipt-help">Formatos permitidos: JPG, PNG o PDF; máximo 5 MB.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="primary-button" type="submit" disabled={enviando}>{enviando ? 'Enviando comprobante...' : 'Enviar comprobante a revisión'}</button>
    </form>}
    {enviado && <button className="primary-button" onClick={onNuevaInscripcion}>Registrar otro robot <span aria-hidden="true">→</span></button>}
    <button className="secondary-button" type="button" onClick={onVerOrdenes}>Ver mis órdenes de pago</button>
  </div></section>
}
