import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  cargarCategoriasEvento,
  cargarConfiguracionEvento,
  cargarDatosInscripcion,
  crearInscripcion,
} from '../services/inscripcionesApi'
import Confirmacion from './Confirmacion'
import MisOrdenes from './MisOrdenes'
import './Inscripcion.css'

const PATRON_NOMBRE = /^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]*$/
const PATRON_CELULAR = /^\d{10}$/

function normalizarNombre(valor) {
  return valor.replace(/[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]/g, '').slice(0, 30).toLocaleUpperCase('es')
}

function institucionValida(institucion) {
  return institucion.name.length <= 30 && PATRON_NOMBRE.test(institucion.name)
}

function integranteVacio(role) {
  return { role, first_name: '', last_name: '', institution_id: '', mobile_phone: '' }
}

function rosterInicial(reglas) {
  const minParticipantes = Math.max(1, Number(reglas?.min_participants ?? 1))
  const minCoaches = Math.max(0, Number(reglas?.min_coaches ?? 0))
  return [
    ...Array.from({ length: minParticipantes }, () => integranteVacio('PARTICIPANT')),
    ...Array.from({ length: minCoaches }, () => integranteVacio('COACH')),
  ]
}

function rangoRoster(minimo, maximo) {
  const min = Number(minimo ?? 0)
  const max = Number(maximo ?? min)
  return min === max ? String(min) : `${min}–${max}`
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
  const [categorias, setCategorias] = useState([])
  const [categoriaId, setCategoriaId] = useState('')
  const [equipo, setEquipo] = useState('')
  const [robot, setRobot] = useState('')
  const [integrantes, setIntegrantes] = useState([])
  const [rosterCategoriaKey, setRosterCategoriaKey] = useState('')
  const [errores, setErrores] = useState({})
  const [cargando, setCargando] = useState(Boolean(token))
  const [enviando, setEnviando] = useState(false)
  const [registro, setRegistro] = useState(null)
  const [vista, setVista] = useState('formulario')
  const [pasoFormulario, setPasoFormulario] = useState(1)
  const [toast, setToast] = useState('')

  useEffect(() => {
    if (!toast) return undefined
    const timeout = window.setTimeout(() => setToast(''), 3200)
    return () => window.clearTimeout(timeout)
  }, [toast])

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
    setConfiguracion(null)
    setCategorias([])
    setIntegrantes([])
    setRosterCategoriaKey('')
    Promise.all([cargarConfiguracionEvento(eventoId), cargarCategoriasEvento(eventoId)])
      .then(([respuesta, reglasCategorias]) => {
        if (!activo) return
        setConfiguracion(respuesta)
        setCategorias(Array.isArray(reglasCategorias) ? reglasCategorias : [])
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
  const reglasCategoria = categorias.find(
    (item) => String(item.category_id) === categoriaSeleccionadaId && item.is_active,
  )
  const rosterCategoriaActual = `${eventoId}:${categoriaSeleccionadaId}`
  const rosterListo = Boolean(reglasCategoria && rosterCategoriaKey === rosterCategoriaActual)
  const registroAbierto = Boolean(configuracionEvento?.registration_open && configuracionEvento?.is_enabled)
  const institucionesDisponibles = (datos?.instituciones || []).filter(institucionValida)

  useEffect(() => {
    if (!reglasCategoria || !categoriaSeleccionadaId || rosterCategoriaKey === rosterCategoriaActual) return
    setIntegrantes(rosterInicial(reglasCategoria))
    setRosterCategoriaKey(rosterCategoriaActual)
    setErrores((actuales) => ({ ...actuales, integrantes: null, roster: '', servidor: '' }))
  }, [reglasCategoria, categoriaSeleccionadaId, rosterCategoriaActual, rosterCategoriaKey])

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

  function ajustarRoster(role, delta) {
    const minimo = role === 'COACH'
      ? Number(reglasCategoria?.min_coaches ?? 0)
      : Math.max(1, Number(reglasCategoria?.min_participants ?? 1))
    const maximo = role === 'COACH'
      ? Number(reglasCategoria?.max_coaches ?? 0)
      : Number(reglasCategoria?.max_participants ?? minimo)
    const cantidadActual = integrantes.filter((item) => item.role === role).length
    if (delta > 0 && cantidadActual >= maximo) {
      setToast(`Acción no permitida. El máximo es ${maximo} ${role === 'COACH' ? 'coach' : 'participantes'}.`)
      return
    }
    setIntegrantes((actuales) => {
      const cantidad = actuales.filter((item) => item.role === role).length
      if (delta > 0 && cantidad < maximo) {
        const nuevo = integranteVacio(role)
        if (role === 'PARTICIPANT') {
          const primerCoach = actuales.findIndex((item) => item.role === 'COACH')
          const insercion = primerCoach < 0 ? actuales.length : primerCoach
          return [...actuales.slice(0, insercion), nuevo, ...actuales.slice(insercion)]
        }
        return [...actuales, nuevo]
      }
      if (delta < 0 && cantidad > minimo) {
        const indice = actuales.map((item) => item.role).lastIndexOf(role)
        return actuales.filter((_, posicion) => posicion !== indice)
      }
      return actuales
    })
    setErrores((actuales) => ({ ...actuales, integrantes: null, roster: '', servidor: '' }))
  }

  async function manejarEnvio(evento) {
    evento.preventDefault()
    const nuevosErrores = {}
    if (!equipo.trim()) nuevosErrores.equipo = 'Ingresa el nombre del equipo.'
    else if (equipo.trim().length > 30) nuevosErrores.equipo = 'Usa máximo 30 caracteres.'
    if (!robot.trim()) nuevosErrores.robot = 'Ingresa el nombre del robot.'
    else if (robot.trim().length > 30) nuevosErrores.robot = 'Usa máximo 30 caracteres.'
    if (!eventoId) nuevosErrores.evento = 'No hay un evento disponible para inscripción.'
    if (!categoriaSeleccionadaId || !tarifa) nuevosErrores.tarifa = 'No existe una tarifa vigente para este evento y categoría.'
    if (configuracionEvento && !registroAbierto) {
      nuevosErrores.configuracion = 'Las inscripciones para este evento no están abiertas.'
    }
    if (!reglasCategoria || !rosterListo) {
      nuevosErrores.roster = 'No se han cargado las reglas de integrantes para esta categoría.'
    } else {
      const cantidadParticipantes = integrantes.filter((item) => item.role === 'PARTICIPANT').length
      const cantidadCoaches = integrantes.filter((item) => item.role === 'COACH').length
      if (cantidadParticipantes < reglasCategoria.min_participants || cantidadParticipantes > reglasCategoria.max_participants
        || cantidadCoaches < reglasCategoria.min_coaches || cantidadCoaches > reglasCategoria.max_coaches) {
        nuevosErrores.roster = 'La cantidad de participantes o coaches no cumple las reglas de esta categoría.'
      }
      const erroresRoster = erroresIntegrantes(integrantes, institucionesDisponibles)
      if (erroresRoster.some((item) => Object.keys(item).length)) nuevosErrores.integrantes = erroresRoster
    }
    setErrores(nuevosErrores)
    if (Object.keys(nuevosErrores).length) {
      setPasoFormulario(nuevosErrores.evento || nuevosErrores.tarifa || nuevosErrores.configuracion ? 1 : 2)
      return
    }

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
      const campo = error.field === 'teamName' ? 'equipo' : error.field === 'robotName' ? 'robot' : null
      setErrores(campo ? { [campo]: error.message } : { servidor: error.message })
      if (campo) setPasoFormulario(2)
    } finally {
      setEnviando(false)
    }
  }

  function continuarRevision() {
    const errorEquipo = !equipo.trim() ? 'Ingresa el nombre del equipo.' : equipo.trim().length > 30 ? 'Usa máximo 30 caracteres.' : ''
    const errorRobot = !robot.trim() ? 'Ingresa el nombre del robot.' : robot.trim().length > 30 ? 'Usa máximo 30 caracteres.' : ''
    let errorRoster = ''
    let erroresMiembros = null
    if (!reglasCategoria || !rosterListo) {
      errorRoster = 'Espera a que se carguen las reglas de integrantes.'
    } else {
      const participantes = integrantes.filter((item) => item.role === 'PARTICIPANT').length
      const coaches = integrantes.filter((item) => item.role === 'COACH').length
      if (participantes < reglasCategoria.min_participants || participantes > reglasCategoria.max_participants
        || coaches < reglasCategoria.min_coaches || coaches > reglasCategoria.max_coaches) {
        errorRoster = 'La cantidad de participantes o coaches no cumple las reglas de esta categoría.'
      }
      erroresMiembros = erroresIntegrantes(integrantes, institucionesDisponibles)
      if (erroresMiembros.some((item) => Object.keys(item).length)) errorRoster ||= 'Completa o corrige los datos de cada integrante.'
    }
    setErrores((actuales) => ({ ...actuales, equipo: errorEquipo, robot: errorRobot, roster: errorRoster, integrantes: erroresMiembros }))
    if (errorEquipo || errorRobot || errorRoster) return
    setErrores((actuales) => ({ ...actuales, equipo: '', robot: '', roster: '', integrantes: null }))
    setPasoFormulario(3)
  }

  function nuevaInscripcion() {
    setEquipo('')
    setRobot('')
    setIntegrantes(reglasCategoria ? rosterInicial(reglasCategoria) : [])
    setRosterCategoriaKey(rosterCategoriaActual)
    setErrores({})
    setRegistro(null)
    setVista('formulario')
    setPasoFormulario(1)
  }

  if (!token) {
    return <section className="registration-section"><div className="registration-card confirmation-card"><span className="eyebrow">ACCESO REQUERIDO</span><h1>Inicia sesión para inscribirte</h1><p>La inscripción se asocia a tu cuenta de participante para proteger tus datos y gestionar el pago.</p><Link className="primary-button registration-link" to="/participante" state={{ from: '/inscripcion' }}>Iniciar sesión como participante</Link></div></section>
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

      <div className="registration-progress" aria-label={`Paso ${pasoFormulario} de 3`}>
        <div className="registration-progress-heading"><span>Inscripción</span><strong>Paso {pasoFormulario} de 3</strong></div>
        <ol>
          {[['Evento', 'event'], ['Equipo e integrantes', 'team'], ['Revisión', 'review']].map(([label, key], index) => (
            <li key={key} className={pasoFormulario === index + 1 ? 'is-current' : pasoFormulario > index + 1 ? 'is-complete' : ''}
              aria-current={pasoFormulario === index + 1 ? 'step' : undefined}>
              <span>{index + 1}</span>{label}
            </li>
          ))}
        </ol>
      </div>
      {errores.servidor && <p className="form-error" role="alert">{errores.servidor}</p>}

      {pasoFormulario === 1 && <>
      <div className="form-grid">
        <label htmlFor="evento">Evento
          <select id="evento" value={eventoId} onChange={(event) => {
            setEventoId(event.target.value)
            setCategoriaId('')
            setErrores((actuales) => ({ ...actuales, configuracion: '', evento: '', tarifa: '', roster: '' }))
          }} disabled={!datos?.eventos.length}>
            {datos?.eventos.map((evento) => <option key={evento.id} value={evento.id}>{evento.name} {evento.edition_year}</option>)}
          </select>
        </label>
        <label htmlFor="categoria">Categoría
          <select id="categoria" value={categoriaSeleccionadaId} onChange={(event) => {
            setCategoriaId(event.target.value)
            setRosterCategoriaKey('')
            setErrores((actuales) => ({ ...actuales, tarifa: '', roster: '', servidor: '' }))
          }} disabled={cargandoConfiguracion || !configuracionEvento?.tariffs.length}>
            {!configuracionEvento?.tariffs.length && <option value="">Sin categorías con tarifa vigente</option>}
            {configuracionEvento?.tariffs.map((item) => (
              <option key={item.category_id} value={item.category_id}>{item.category}</option>
            ))}
          </select>
        </label>
      </div>

      {errores.configuracion && <p className="form-error" role="alert">{errores.configuracion}</p>}
      {errores.evento && <p className="form-error" role="alert">{errores.evento}</p>}
      {errores.tarifa && <p className="form-error" role="alert">{errores.tarifa}</p>}
      {configuracionEvento && !registroAbierto && <p className="registration-closed" role="status">Las inscripciones de este evento están cerradas o deshabilitadas.</p>}
      <button className="primary-button" type="button" onClick={() => {
        if (!eventoId) { setErrores((actuales) => ({ ...actuales, evento: 'Selecciona un evento.' })); return }
        if (!categoriaSeleccionadaId || !tarifa) { setErrores((actuales) => ({ ...actuales, tarifa: 'Selecciona una categoría con tarifa vigente.' })); return }
        if (!registroAbierto) { setErrores((actuales) => ({ ...actuales, configuracion: 'Las inscripciones para este evento no están abiertas.' })); return }
        setErrores((actuales) => ({ ...actuales, evento: '', tarifa: '', configuracion: '' }))
        setPasoFormulario(2)
      }}>Continuar con el equipo <span aria-hidden="true"> →</span></button>
      </>}

      {pasoFormulario === 2 && <>
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
        {reglasCategoria ? (
          <p>Participantes: {rangoRoster(reglasCategoria.min_participants, reglasCategoria.max_participants)} · Coaches: {rangoRoster(reglasCategoria.min_coaches, reglasCategoria.max_coaches)}.</p>
        ) : <p>Cargando los límites de integrantes de la categoría...</p>}
      </div>

      {rosterListo && integrantes.map((integrante, index) => {
        const indiceRol = integrantes.slice(0, index).filter((item) => item.role === integrante.role).length + 1
        const nombre = integrante.role === 'COACH' ? `Coach ${indiceRol}` : `Participante ${indiceRol}`
        const sufijo = integrante.role === 'COACH' ? `coach-${indiceRol}` : `participante-${indiceRol}`
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

      {rosterListo && (() => {
        const participantes = integrantes.filter((item) => item.role === 'PARTICIPANT').length
        const coaches = integrantes.filter((item) => item.role === 'COACH').length
        return <div className="roster-actions">
          <button type="button" className="participant-mode-toggle" onClick={() => ajustarRoster('PARTICIPANT', 1)}>Añadir participante</button>
          {participantes > Math.max(1, reglasCategoria.min_participants) && <button type="button" className="participant-mode-toggle" onClick={() => ajustarRoster('PARTICIPANT', -1)}>Quitar participante</button>}
          <button type="button" className="participant-mode-toggle" onClick={() => ajustarRoster('COACH', 1)}>Añadir coach</button>
          {coaches > reglasCategoria.min_coaches && <button type="button" className="participant-mode-toggle" onClick={() => ajustarRoster('COACH', -1)}>Quitar coach</button>}
        </div>
      })()}

      {errores.roster && <p className="form-error" role="alert">{errores.roster}</p>}
      <div className="registration-step-actions">
        <button className="secondary-button" type="button" onClick={() => setPasoFormulario(1)}>Volver al evento</button>
        <button className="primary-button" type="button" onClick={continuarRevision} disabled={!rosterListo}>
          Revisar datos <span aria-hidden="true"> →</span>
        </button>
      </div>
      </>}

      {pasoFormulario === 3 && <>
        <section className="registration-review" aria-labelledby="registration-review-title">
          <h2 id="registration-review-title">Revisa la inscripción</h2>
          <p>Confirma que los datos del evento y del equipo estén correctos antes de crear la orden de pago.</p>
          <dl>
            <div><dt>Evento</dt><dd>{datos?.eventos.find((evento) => String(evento.id) === eventoId)?.name || '—'}</dd></div>
            <div><dt>Categoría</dt><dd>{tarifa?.category || '—'}</dd></div>
            <div><dt>Equipo</dt><dd>{equipo || '—'}</dd></div>
            <div><dt>Robot</dt><dd>{robot || '—'}</dd></div>
            <div><dt>Participantes y coaches</dt><dd>{integrantes.filter((item) => item.role === 'PARTICIPANT').length} participantes · {integrantes.filter((item) => item.role === 'COACH').length} coaches</dd></div>
            <div><dt>Total de inscripción</dt><dd>{tarifa ? `${configuracionEvento.currency || 'USD'} ${Number(tarifa.amount).toFixed(2)}` : '—'}</dd></div>
          </dl>
        </section>
        <div className="registration-step-actions">
          <button className="secondary-button" type="button" onClick={() => setPasoFormulario(2)}>Volver a editar el equipo</button>
      <button className="primary-button" type="submit"
        disabled={enviando || cargandoConfiguracion || !datos || !registroAbierto || !tarifa || !rosterListo}>
        {enviando ? 'Creando inscripción...' : 'Crear inscripción y orden de pago'}
        {!enviando && <span aria-hidden="true"> →</span>}
      </button>
        </div>
      </>}
    </form>
    {toast && <div className="registration-toast" role="alert" aria-live="assertive">{toast}</div>}
  </section>
}
