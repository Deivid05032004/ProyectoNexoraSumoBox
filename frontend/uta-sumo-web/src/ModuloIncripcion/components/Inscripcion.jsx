import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  cargarConfiguracionEvento,
  cargarDatosInscripcion,
  crearInscripcion,
} from '../services/inscripcionesApi'
import Confirmacion from './Confirmacion'
import MisOrdenes from './MisOrdenes'
import './Inscripcion.css'

const NUEVOS_INTEGRANTES = [
  { role: 'PARTICIPANT', first_name: '', last_name: '', institution_id: '', mobile_phone: '' },
  { role: 'PARTICIPANT', first_name: '', last_name: '', institution_id: '', mobile_phone: '' },
  { role: 'COACH', first_name: '', last_name: '', institution_id: '', mobile_phone: '' },
]
const PATRON_NOMBRE = /^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]*$/
const PATRON_CELULAR = /^\d{10}$/

function normalizarNombre(valor) {
  return valor.replace(/[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]/g, '').slice(0, 30).toLocaleUpperCase('es')
}

function institucionValida(institucion) {
  return institucion.name.length <= 30 && PATRON_NOMBRE.test(institucion.name)
}

function integrantesIniciales() {
  return NUEVOS_INTEGRANTES.map((integrante) => ({ ...integrante }))
}

function erroresIntegrantes(integrantes, instituciones) {
  const errores = integrantes.map((integrante) => {
    const erroresCampo = {}
    if (!integrante.first_name.trim()) erroresCampo.first_name = 'Ingresa los nombres.'
    else if (integrante.first_name.length > 30 || !PATRON_NOMBRE.test(integrante.first_name)) {
      erroresCampo.first_name = 'Usa solo letras y espacios; máximo 30 caracteres.'
    }
    if (!integrante.last_name.trim()) erroresCampo.last_name = 'Ingresa los apellidos.'
    else if (integrante.last_name.length > 30 || !PATRON_NOMBRE.test(integrante.last_name)) {
      erroresCampo.last_name = 'Usa solo letras y espacios; máximo 30 caracteres.'
    }
    const institucion = instituciones.find((item) => String(item.id) === integrante.institution_id)
    if (!institucion) erroresCampo.institution_id = 'Selecciona una institución válida.'
    else if (!institucionValida(institucion)) {
      erroresCampo.institution_id = 'La institución debe tener máximo 30 caracteres y solo letras y espacios.'
    }
    if (!integrante.mobile_phone) {
      erroresCampo.mobile_phone = 'Ingresa el número celular.'
    } else if (!PATRON_CELULAR.test(integrante.mobile_phone)) {
      erroresCampo.mobile_phone = 'Ingresa exactamente 10 dígitos.'
    }
    return erroresCampo
  })

  if (errores.some((item) => Object.keys(item).length)) return errores

  const identidad = (integrante) => [
    integrante.first_name.trim().toLocaleLowerCase(),
    integrante.last_name.trim().toLocaleLowerCase(),
    integrante.institution_id,
    integrante.mobile_phone.trim().toLocaleLowerCase(),
  ].join('|')
  const identidades = new Set()
  integrantes.forEach((integrante, index) => {
    const clave = identidad(integrante)
    if (identidades.has(clave)) {
      errores[index].first_name = 'No repitas los datos de otro integrante.'
    }
    identidades.add(clave)
  })
  if (errores.some((item) => Object.keys(item).length)) {
    return errores
  }
  return errores
}

export default function Inscripcion() {
  const token = sessionStorage.getItem('uta.access_token')
  const [datos, setDatos] = useState(null)
  const [eventoId, setEventoId] = useState('')
  const [configuracion, setConfiguracion] = useState(null)
  const [categoriaId, setCategoriaId] = useState('')
  const [equipo, setEquipo] = useState('')
  const [robot, setRobot] = useState('')
  const [integrantes, setIntegrantes] = useState(integrantesIniciales)
  const [errores, setErrores] = useState({})
  const [cargando, setCargando] = useState(Boolean(token))
  const [enviando, setEnviando] = useState(false)
  const [registro, setRegistro] = useState(null)
  const [vista, setVista] = useState('formulario')

  useEffect(() => {
    if (!token) return undefined
    let activo = true
    cargarDatosInscripcion(token)
      .then((respuesta) => {
        if (!activo) return
        setDatos(respuesta)
        setEventoId(respuesta.eventos[0] ? String(respuesta.eventos[0].id) : '')
      })
      .catch((error) => activo && setErrores({ servidor: error.message }))
      .finally(() => activo && setCargando(false))
    return () => { activo = false }
  }, [token])

  useEffect(() => {
    if (!eventoId) return undefined
    let activo = true
    cargarConfiguracionEvento(eventoId)
      .then((respuesta) => {
        if (!activo) return
        setConfiguracion(respuesta)
      })
      .catch((error) => activo && setErrores((actuales) => ({ ...actuales, configuracion: error.message })))
    return () => { activo = false }
  }, [eventoId])

  const configuracionEvento = configuracion?.event_id === Number(eventoId) ? configuracion : null
  const cargandoConfiguracion = Boolean(eventoId) && !configuracionEvento && !errores.configuracion
  const categoriaSeleccionadaId = configuracionEvento?.tariffs.some(
    (item) => String(item.category_id) === categoriaId,
  )
    ? categoriaId
    : String(configuracionEvento?.tariffs[0]?.category_id || '')
  const tarifa = configuracionEvento?.tariffs.find(
    (item) => String(item.category_id) === categoriaSeleccionadaId,
  )
  const registroAbierto = Boolean(configuracionEvento?.registration_open && configuracionEvento?.is_enabled)
  const institucionesDisponibles = (datos?.instituciones || []).filter(institucionValida)

  function actualizarIntegrante(index, campo, valor) {
    setIntegrantes((actuales) => actuales.map((integrante, posicion) => (
      posicion === index ? { ...integrante, [campo]: valor } : integrante
    )))
    setErrores((actuales) => {
      const campos = [...(actuales.integrantes || [])]
      campos[index] = { ...campos[index], [campo]: '' }
      return { ...actuales, integrantes: campos }
    })
  }

  async function manejarEnvio(evento) {
    evento.preventDefault()
    const nuevosErrores = {}
    if (!equipo.trim()) nuevosErrores.equipo = 'Ingresa el nombre del equipo.'
    if (!robot.trim()) nuevosErrores.robot = 'Ingresa el nombre del robot.'
    if (!eventoId) nuevosErrores.evento = 'No hay un evento disponible para inscripción.'
    if (!categoriaSeleccionadaId || !tarifa) nuevosErrores.tarifa = 'No existe una tarifa vigente para este evento y categoría.'
    if (configuracionEvento && !registroAbierto) {
      nuevosErrores.configuracion = 'Las inscripciones para este evento no están abiertas.'
    }
    const erroresRoster = erroresIntegrantes(integrantes, institucionesDisponibles)
    if (erroresRoster.some((item) => Object.keys(item).length)) nuevosErrores.integrantes = erroresRoster
    setErrores(nuevosErrores)
    if (Object.keys(nuevosErrores).length) return

    setEnviando(true)
    try {
      const respuesta = await crearInscripcion({
        token,
        eventId: eventoId,
        categoryId: categoriaSeleccionadaId,
        participant: datos.participante,
        teamName: equipo.trim(),
        robotName: robot.trim(),
        participants: integrantes,
      })
      setRegistro(respuesta)
    } catch (error) {
      setErrores({ servidor: error.message })
    } finally {
      setEnviando(false)
    }
  }

  function nuevaInscripcion() {
    setEquipo('')
    setRobot('')
    setIntegrantes(integrantesIniciales())
    setErrores({})
    setRegistro(null)
    setVista('formulario')
  }

  if (!token) {
    return <section className="registration-section"><div className="registration-card confirmation-card"><span className="eyebrow">ACCESO REQUERIDO</span><h1>Inicia sesión para inscribirte</h1><p>La inscripción se asocia a tu cuenta de participante para proteger tus datos y gestionar el pago.</p><Link className="primary-button registration-link" to="/participante">Iniciar sesión como participante</Link></div></section>
  }

  if (cargando) return <section className="registration-section"><div className="registration-card"><p>Cargando datos de inscripción...</p></div></section>
  if (vista === 'ordenes') {
    return <MisOrdenes token={token} onCrearInscripcion={() => setVista('formulario')} />
  }
  if (registro) {
    return (
      <Confirmacion
        registro={registro}
        configuracion={configuracionEvento}
        token={token}
        onNuevaInscripcion={nuevaInscripcion}
        onVerOrdenes={() => {
          setRegistro(null)
          setVista('ordenes')
        }}
      />
    )
  }

  return <section className="registration-section" id="inscripcion">
    <div className="registration-view-switch" role="group" aria-label="Sección de inscripciones">
      <button className="secondary-button" type="button" aria-pressed={vista === 'formulario'} onClick={() => setVista('formulario')}>Crear inscripción</button>
      <button className="secondary-button" type="button" aria-pressed={vista === 'ordenes'} onClick={() => setVista('ordenes')}>Mis órdenes de pago</button>
    </div>
    <div className="section-heading">
      <span className="eyebrow">{configuracionEvento?.organization_name || 'REGISTRO OFICIAL'}</span>
      <h1>{configuracionEvento?.form_title || 'Inscripción al evento'}</h1>
      <p>{configuracionEvento?.form_description || 'Completa los datos del equipo, robot y roster para generar la inscripción y la orden de pago.'}</p>
      {configuracionEvento?.form_instructions && <p className="registration-instructions">{configuracionEvento.form_instructions}</p>}
    </div>
    <form className="registration-card" onSubmit={manejarEnvio} noValidate>
      <div className="registration-summary">
        <div>
          <span>Evento</span>
          <strong>{datos?.eventos.find((evento) => String(evento.id) === eventoId)?.name || 'Selecciona un evento'}</strong>
        </div>
        <div>
          <span>Valor de inscripción</span>
          <strong>{tarifa ? `${configuracionEvento.currency || 'USD'} ${Number(tarifa.amount).toFixed(2)}` : 'Sin tarifa vigente'}</strong>
          <small>La tarifa vigente se consulta desde la configuración del evento.</small>
        </div>
      </div>

      <div className="form-grid">
        <label htmlFor="evento">Evento
          <select id="evento" value={eventoId} onChange={(event) => {
            setEventoId(event.target.value)
            setCategoriaId('')
            setErrores((actuales) => ({ ...actuales, configuracion: '', evento: '', tarifa: '' }))
          }} disabled={!datos?.eventos.length}>
            {datos?.eventos.map((evento) => <option key={evento.id} value={evento.id}>{evento.name} {evento.edition_year}</option>)}
          </select>
        </label>
        <label htmlFor="categoria">Categoría
          <select id="categoria" value={categoriaSeleccionadaId} onChange={(event) => {
            setCategoriaId(event.target.value)
            setErrores((actuales) => ({ ...actuales, tarifa: '' }))
          }} disabled={cargandoConfiguracion || !configuracionEvento?.tariffs.length}>
            {!configuracionEvento?.tariffs.length && <option value="">Sin categorías con tarifa vigente</option>}
            {configuracionEvento?.tariffs.map((item) => (
              <option key={item.category_id} value={item.category_id}>{item.category}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="form-grid">
        <label htmlFor="equipo">Nombre del equipo
          <input id="equipo" maxLength="30" value={equipo} onChange={(event) => {
            setEquipo(event.target.value.toUpperCase())
            setErrores((actuales) => ({ ...actuales, equipo: '' }))
          }} aria-invalid={Boolean(errores.equipo)} />
          {errores.equipo && <span className="field-error">{errores.equipo}</span>}
        </label>
        <label htmlFor="robot">Nombre del robot
          <input id="robot" maxLength="30" value={robot} onChange={(event) => {
            setRobot(event.target.value.toUpperCase())
            setErrores((actuales) => ({ ...actuales, robot: '' }))
          }} aria-invalid={Boolean(errores.robot)} />
          {errores.robot && <span className="field-error">{errores.robot}</span>}
        </label>
      </div>

      <div className="members-heading">
        <h2>Integrantes de la inscripción</h2>
        <p>Ingresa los datos de los dos participantes y del coach que conforman el equipo.</p>
      </div>

      {integrantes.map((integrante, index) => {
        const nombre = integrante.role === 'COACH' ? 'Coach' : `Participante ${index + 1}`
        const sufijo = integrante.role === 'COACH' ? 'coach' : `participante-${index + 1}`
        const errorCampo = errores.integrantes?.[index] || {}
        return (
          <fieldset className="member-fields" key={sufijo}>
            <legend>{nombre}</legend>
            <div className="form-grid form-grid-two">
              <label htmlFor={`${sufijo}-nombres`}>Nombres
                <input id={`${sufijo}-nombres`} maxLength="30" value={integrante.first_name}
                  onChange={(event) => actualizarIntegrante(index, 'first_name', normalizarNombre(event.target.value))}
                  aria-invalid={Boolean(errorCampo.first_name)} aria-describedby={errorCampo.first_name ? `${sufijo}-nombres-error` : undefined} />
                {errorCampo.first_name && <span id={`${sufijo}-nombres-error`} className="field-error">{errorCampo.first_name}</span>}
              </label>
              <label htmlFor={`${sufijo}-apellidos`}>Apellidos
                <input id={`${sufijo}-apellidos`} maxLength="30" value={integrante.last_name}
                  onChange={(event) => actualizarIntegrante(index, 'last_name', normalizarNombre(event.target.value))}
                  aria-invalid={Boolean(errorCampo.last_name)} aria-describedby={errorCampo.last_name ? `${sufijo}-apellidos-error` : undefined} />
                {errorCampo.last_name && <span id={`${sufijo}-apellidos-error`} className="field-error">{errorCampo.last_name}</span>}
              </label>
            </div>
            <div className="form-grid form-grid-two">
              <label htmlFor={`${sufijo}-institucion`}>Institución
                <select id={`${sufijo}-institucion`} value={integrante.institution_id}
                  onChange={(event) => actualizarIntegrante(index, 'institution_id', event.target.value)}
                  aria-invalid={Boolean(errorCampo.institution_id)} aria-describedby={errorCampo.institution_id ? `${sufijo}-institucion-error` : undefined}>
                  <option value="">Selecciona una institución</option>
                  {institucionesDisponibles.map((institucion) => (
                    <option key={institucion.id} value={institucion.id}>{institucion.name.toLocaleUpperCase('es')}</option>
                  ))}
                </select>
                {errorCampo.institution_id && <span id={`${sufijo}-institucion-error`} className="field-error">{errorCampo.institution_id}</span>}
              </label>
              <label htmlFor={`${sufijo}-celular`}>Número celular
                <input id={`${sufijo}-celular`} type="tel" inputMode="numeric" maxLength="10"
                  pattern="[0-9]{10}" placeholder="10 dígitos" value={integrante.mobile_phone} required
                  onChange={(event) => actualizarIntegrante(index, 'mobile_phone', event.target.value.replace(/\D/g, '').slice(0, 10))}
                  aria-invalid={Boolean(errorCampo.mobile_phone)} aria-describedby={errorCampo.mobile_phone ? `${sufijo}-celular-error` : undefined} />
                {errorCampo.mobile_phone && <span id={`${sufijo}-celular-error`} className="field-error">{errorCampo.mobile_phone}</span>}
              </label>
            </div>
          </fieldset>
        )
      })}

      {errores.configuracion && <p className="form-error" role="alert">{errores.configuracion}</p>}
      {configuracionEvento && !registroAbierto && <p className="registration-closed" role="status">Las inscripciones de este evento están cerradas o deshabilitadas.</p>}
      {errores.servidor && <p className="form-error" role="alert">{errores.servidor}</p>}
      <button className="primary-button" type="submit"
        disabled={enviando || cargandoConfiguracion || !datos || !registroAbierto || !tarifa}>
        {enviando ? 'Creando inscripción...' : 'Crear inscripción y orden de pago'}
        {!enviando && <span aria-hidden="true"> →</span>}
      </button>
    </form>
  </section>
}
