import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { cargarDatosInscripcion, cargarTarifa, crearInscripcion } from '../services/inscripcionesApi'
import Confirmacion from './Confirmacion'

const CATEGORIA = 'MINI SUMO RC AMATEUR'

export default function Inscripcion() {
  const token = sessionStorage.getItem('uta.access_token')
  const [datos, setDatos] = useState(null)
  const [eventoId, setEventoId] = useState('')
  const [tarifa, setTarifa] = useState(null)
  const [equipo, setEquipo] = useState('')
  const [robot, setRobot] = useState('')
  const [errores, setErrores] = useState({})
  const [cargando, setCargando] = useState(Boolean(token))
  const [enviando, setEnviando] = useState(false)
  const [registro, setRegistro] = useState(null)

  useEffect(() => {
    if (!token) return
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
    if (!token || !datos || !eventoId) return undefined
    let activo = true
    cargarTarifa(token, eventoId, datos.categoria.id)
      .then((respuesta) => activo && setTarifa(respuesta))
      .catch((error) => activo && setErrores((actuales) => ({ ...actuales, tarifa: error.message })))
    return () => { activo = false }
  }, [token, datos, eventoId])

  function manejarEnvio(evento) {
    evento.preventDefault()
    const nuevosErrores = {}
    if (!equipo.trim()) nuevosErrores.equipo = 'Ingresa el nombre del equipo.'
    if (!robot.trim()) nuevosErrores.robot = 'Ingresa el nombre del robot.'
    if (!eventoId) nuevosErrores.evento = 'No hay un evento disponible para inscripción.'
    if (!tarifa) nuevosErrores.tarifa = 'No existe una tarifa vigente para este evento y categoría.'
    setErrores(nuevosErrores)
    if (Object.keys(nuevosErrores).length) return

    setEnviando(true)
    crearInscripcion({ token, eventId: eventoId, categoryId: datos.categoria.id, participant: datos.participante, teamName: equipo.trim(), robotName: robot.trim() })
      .then(setRegistro)
      .catch((error) => setErrores({ servidor: error.message }))
      .finally(() => setEnviando(false))
  }

  function nuevaInscripcion() {
    setEquipo(''); setRobot(''); setErrores({}); setRegistro(null)
  }

  if (!token) {
    return <section className="registration-section"><div className="registration-card confirmation-card"><span className="eyebrow">ACCESO REQUERIDO</span><h1>Inicia sesión para inscribirte</h1><p>La inscripción se asocia a tu cuenta de participante para proteger tus datos y gestionar el pago.</p><Link className="primary-button registration-link" to="/participante">Iniciar sesión como participante</Link></div></section>
  }

  if (cargando) return <section className="registration-section"><div className="registration-card"><p>Cargando datos de inscripción...</p></div></section>
  if (registro) return <Confirmacion registro={registro} token={token} onNuevaInscripcion={nuevaInscripcion} />

  return <section className="registration-section" id="inscripcion">
    <div className="section-heading"><span className="eyebrow">REGISTRO OFICIAL</span><h1>UTA SUMO ROBOTICS CUP</h1><p>Primero se genera tu inscripción y orden de pago. Después podrás adjuntar el comprobante para revisión.</p></div>
    <form className="registration-card" onSubmit={manejarEnvio} noValidate>
      <div className="registration-summary">
        <div><span>Categoría</span><strong>{CATEGORIA}</strong></div>
        <div><span>Valor de inscripción</span><strong>{tarifa ? `$${Number(tarifa.amount).toFixed(2)}` : 'Sin tarifa vigente'}</strong><small>La tarifa se consulta directamente al sistema.</small></div>
      </div>
      <div className="form-grid">
        <label htmlFor="evento">Evento<select id="evento" value={eventoId} onChange={(event) => { setEventoId(event.target.value); setTarifa(null); setErrores((actuales) => ({ ...actuales, tarifa: '' })) }} disabled={!datos?.eventos.length}>{datos?.eventos.map((evento) => <option key={evento.id} value={evento.id}>{evento.name} {evento.edition_year}</option>)}</select>{errores.evento && <span className="field-error">{errores.evento}</span>}</label>
        <label htmlFor="equipo">Nombre del equipo<input id="equipo" maxLength="120" value={equipo} onChange={(event) => { setEquipo(event.target.value.toUpperCase()); setErrores((actuales) => ({ ...actuales, equipo: '' })) }} aria-invalid={Boolean(errores.equipo)} />{errores.equipo && <span className="field-error">{errores.equipo}</span>}</label>
      </div>
      <div className="form-grid"><label htmlFor="robot">Nombre del robot<input id="robot" maxLength="120" value={robot} onChange={(event) => { setRobot(event.target.value.toUpperCase()); setErrores((actuales) => ({ ...actuales, robot: '' })) }} aria-invalid={Boolean(errores.robot)} />{errores.robot && <span className="field-error">{errores.robot}</span>}</label></div>
      <div className="members-heading"><h2>Participante asociado</h2><p>La inscripción se asociará al perfil de la cuenta que inició sesión.</p></div>
      <fieldset className="member-fields"><legend>Datos de tu perfil</legend><div className="form-grid form-grid-three"><label>Nombres y apellidos<input value={datos?.participante ? `${datos.participante.first_name} ${datos.participante.last_name}` : ''} readOnly /></label><label>Institución<input value={datos?.instituciones.find((item) => item.id === datos.participante.institution_id)?.name || ''} readOnly /></label><label>Número celular<input value={datos?.participante?.mobile_phone || 'No registrado'} readOnly /></label></div></fieldset>
      {/*
        Campos propuestos para revisar con el equipo cuando el backend permita
        vincular perfiles de otros integrantes a la inscripción:
        <fieldset className="member-fields">
          <legend>Participante 1</legend>
          <input name="participant1_first_name" placeholder="Nombres" />
          <input name="participant1_last_name" placeholder="Apellidos" />
          <input name="participant1_institution" placeholder="Institución" />
          <input name="participant1_mobile_phone" placeholder="Número celular" />
        </fieldset>
        <fieldset className="member-fields">
          <legend>Participante 2</legend>
          <input name="participant2_first_name" placeholder="Nombres" />
          <input name="participant2_last_name" placeholder="Apellidos" />
          <input name="participant2_institution" placeholder="Institución" />
          <input name="participant2_mobile_phone" placeholder="Número celular" />
        </fieldset>
        <fieldset className="member-fields">
          <legend>Coach</legend>
          <input name="coach_first_name" placeholder="Nombres" />
          <input name="coach_last_name" placeholder="Apellidos" />
          <input name="coach_institution" placeholder="Institución" />
          <input name="coach_mobile_phone" placeholder="Número celular" />
        </fieldset>
      */}
      {errores.tarifa && <p className="form-error" role="alert">{errores.tarifa}</p>}
      {errores.servidor && <p className="form-error" role="alert">{errores.servidor}</p>}
      <button className="primary-button" type="submit" disabled={enviando || !datos}>{enviando ? 'Creando inscripción...' : 'Crear inscripción y orden de pago'} {!enviando && <span aria-hidden="true">→</span>}</button>
    </form>
  </section>
}
