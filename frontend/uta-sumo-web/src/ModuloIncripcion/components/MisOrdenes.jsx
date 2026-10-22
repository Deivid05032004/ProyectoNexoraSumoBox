import { useCallback, useEffect, useState } from 'react'
import { cargarMisOrdenes, descargarInstruccionesPago, subirComprobante } from '../services/inscripcionesApi'
import './MisOrdenes.css'

const TIPOS_COMPROBANTE = ['image/jpeg', 'image/png', 'application/pdf']
const TAMANIO_MAXIMO_ARCHIVO = 5 * 1024 * 1024

function validarArchivo(archivo) {
  if (!archivo) return 'Selecciona el comprobante de transferencia.'
  if (!TIPOS_COMPROBANTE.includes(archivo.type)) return 'Solo se aceptan archivos JPG, PNG o PDF.'
  if (archivo.size > TAMANIO_MAXIMO_ARCHIVO) return 'El comprobante no puede superar los 5 MB.'
  return ''
}

function fecha(valor) {
  if (!valor) return 'No disponible'
  return new Intl.DateTimeFormat('es-EC', { dateStyle: 'medium' }).format(new Date(valor))
}

function estadoPago(estado) {
  return ({
    PENDING: 'Pendiente de pago',
    REJECTED: 'Comprobante observado',
    IN_REVIEW: 'En revisión',
    PAID: 'Pagado',
  })[estado] || estado || 'No disponible'
}

export default function MisOrdenes({ token, onCrearInscripcion }) {
  const [ordenes, setOrdenes] = useState([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [archivos, setArchivos] = useState({})
  const [referencias, setReferencias] = useState({})
  const [errores, setErrores] = useState({})
  const [ocupado, setOcupado] = useState(null)

  const cargar = useCallback(async () => {
    try {
      setOrdenes(await cargarMisOrdenes(token))
    } catch (reason) {
      setError(reason.message || 'No se pudieron cargar tus órdenes de pago.')
    } finally {
      setCargando(false)
    }
  }, [token])

  useEffect(() => {
    let activo = true
    cargarMisOrdenes(token)
      .then((respuesta) => activo && setOrdenes(respuesta))
      .catch((reason) => activo && setError(reason.message || 'No se pudieron cargar tus órdenes de pago.'))
      .finally(() => activo && setCargando(false))
    return () => { activo = false }
  }, [token])

  function actualizarOrdenes() {
    setCargando(true)
    setError('')
    cargar()
  }

  async function descargar(orden) {
    setOcupado(`descarga-${orden.id}`)
    setErrores((actuales) => ({ ...actuales, [orden.id]: '' }))
    try {
      await descargarInstruccionesPago({
        ...orden,
        id: orden.registration_id,
        receipt_url: `/api/v1/registrations/${orden.registration_id}/receipt`,
      }, token)
    } catch (reason) {
      setErrores((actuales) => ({ ...actuales, [orden.id]: reason.message || 'No se pudo descargar la orden de pago.' }))
    } finally {
      setOcupado(null)
    }
  }

  async function enviarComprobante(event, orden) {
    event.preventDefault()
    const archivo = archivos[orden.id]
    const errorArchivo = validarArchivo(archivo)
    if (errorArchivo) {
      setErrores((actuales) => ({ ...actuales, [orden.id]: errorArchivo }))
      return
    }
    setOcupado(`comprobante-${orden.id}`)
    setErrores((actuales) => ({ ...actuales, [orden.id]: '' }))
    setError('')
    try {
      await subirComprobante(orden.id, archivo, token, referencias[orden.id] || '')
      setArchivos((actuales) => ({ ...actuales, [orden.id]: null }))
      await cargar()
    } catch (reason) {
      setErrores((actuales) => ({ ...actuales, [orden.id]: reason.message || 'No se pudo enviar el comprobante.' }))
    } finally {
      setOcupado(null)
    }
  }

  return (
    <section className="registration-section my-orders-section">
      <div className="section-heading">
        <span className="eyebrow">CUENTA DE PARTICIPANTE</span>
        <h1>Mis órdenes de pago</h1>
        <p>Consulta tus inscripciones, descarga las instrucciones de pago y adjunta el comprobante cuando lo tengas disponible.</p>
      </div>
      <div className="my-orders-toolbar">
        <button className="secondary-button" type="button" onClick={onCrearInscripcion}>Crear inscripción</button>
        <button className="secondary-button" type="button" onClick={actualizarOrdenes} disabled={cargando}>Actualizar</button>
      </div>

      {cargando && <div className="registration-card"><p>Cargando tus órdenes de pago...</p></div>}
      {!cargando && error && <p className="form-error" role="alert">{error}</p>}
      {!cargando && !error && ordenes.length === 0 && (
        <div className="registration-card my-orders-empty">
          <h2>Aún no tienes órdenes de pago</h2>
          <p>Cuando completes una inscripción, su orden aparecerá aquí.</p>
          <button className="primary-button" type="button" onClick={onCrearInscripcion}>Crear inscripción</button>
        </div>
      )}

      {!cargando && !error && ordenes.map((orden) => {
        const procesando = ocupado === `comprobante-${orden.id}` || ocupado === `descarga-${orden.id}`
        return (
          <article className="registration-card my-order-card" key={orden.id}>
            <div className="my-order-heading">
              <div>
                <span className="my-order-code">Orden {orden.registration_code}</span>
                <h2>{orden.event_name}</h2>
              </div>
              <span className={`my-order-status my-order-status-${orden.status?.toLowerCase()}`}>
                {estadoPago(orden.status)}
              </span>
            </div>
            <dl className="my-order-details">
              <div><dt>Equipo</dt><dd>{orden.team_name}</dd></div>
              <div><dt>Robot</dt><dd>{orden.robot_name}</dd></div>
              <div><dt>Categoría</dt><dd>{orden.category_name}</dd></div>
              <div><dt>Fecha de inscripción</dt><dd>{fecha(orden.registration_created_at)}</dd></div>
              <div><dt>Valor</dt><dd>{orden.currency} {Number(orden.amount).toFixed(2)}</dd></div>
              <div><dt>Comprobante</dt><dd>{orden.has_receipt ? `Recibido: ${fecha(orden.receipt_uploaded_at)}` : 'Aún no enviado'}</dd></div>
            </dl>

            {orden.review_comments && <p className="my-order-review"><strong>Comentario de revisión:</strong> {orden.review_comments}</p>}

            <button className="secondary-button" type="button" disabled={procesando} onClick={() => descargar(orden)}>
              {ocupado === `descarga-${orden.id}` ? 'Descargando...' : 'Descargar orden de pago (PDF)'}
            </button>

            {orden.can_upload_receipt && (
              <form className="my-order-upload" onSubmit={(event) => enviarComprobante(event, orden)} noValidate>
                <h3>{orden.status === 'REJECTED' ? 'Adjunta un comprobante corregido' : '¿Pagarás después? Puedes adjuntar el comprobante cuando lo tengas.'}</h3>
                <label htmlFor={`referencia-${orden.id}`}>Referencia de transferencia (opcional)
                  <input id={`referencia-${orden.id}`} maxLength="150" value={referencias[orden.id] || ''}
                    onChange={(event) => setReferencias((actuales) => ({ ...actuales, [orden.id]: event.target.value }))} />
                </label>
                <label htmlFor={`archivo-${orden.id}`}>Comprobante (JPG, PNG o PDF; máximo 5 MB)
                  <input id={`archivo-${orden.id}`} type="file" accept="image/jpeg,image/png,application/pdf"
                    onChange={(event) => {
                      const archivo = event.target.files?.[0] || null
                      setArchivos((actuales) => ({ ...actuales, [orden.id]: archivo }))
                      setErrores((actuales) => ({ ...actuales, [orden.id]: validarArchivo(archivo) }))
                    }} />
                </label>
                {archivos[orden.id] && <p className="my-order-file">{archivos[orden.id].name}</p>}
                {errores[orden.id] && <p className="form-error" role="alert">{errores[orden.id]}</p>}
                <button className="primary-button" type="submit" disabled={procesando}>
                  {ocupado === `comprobante-${orden.id}` ? 'Enviando comprobante...' : 'Enviar comprobante a revisión'}
                </button>
              </form>
            )}
            {!orden.can_upload_receipt && !errores[orden.id] && orden.status === 'IN_REVIEW' && (
              <p className="my-order-note" role="status">El comprobante fue enviado y está pendiente de revisión.</p>
            )}
            {errores[orden.id] && !orden.can_upload_receipt && <p className="form-error" role="alert">{errores[orden.id]}</p>}
          </article>
        )
      })}
    </section>
  )
}
