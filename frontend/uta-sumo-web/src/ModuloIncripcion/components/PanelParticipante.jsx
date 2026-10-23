import { useEffect, useState } from 'react'
import BienvenidaParticipante from './BienvenidaParticipante'
import Inscripcion from './Inscripcion'
import MisOrdenes from './MisOrdenes'
import {
  cargarCategoriasEvento,
  cargarConfiguracionEvento,
  cargarDatosInscripcion,
} from '../services/inscripcionesApi'
import './PanelParticipante.css'

const SECCIONES = [
  { id: 'inicio', label: 'Inicio' },
  { id: 'inscripcion', label: 'Inscribir mi robot' },
  { id: 'ordenes', label: 'Mis órdenes' },
  { id: 'categorias', label: 'Categorías' },
  { id: 'reglamento', label: 'Reglamento oficial' },
  { id: 'equipo', label: 'Equipo' },
]
const REGLAMENTO_URL = `${import.meta.env.BASE_URL}reglamento-oficial.pdf`

function rango(minimo, maximo) {
  if (minimo == null && maximo == null) return 'No especificado'
  if (minimo != null && maximo != null) return `${minimo}–${maximo}`
  if (minimo != null) return `Mínimo ${minimo}`
  return `Máximo ${maximo}`
}

export default function ParticipantDashboard({ user }) {
  const [seccion, setSeccion] = useState('inicio')
  const [eventos, setEventos] = useState([])
  const [eventoId, setEventoId] = useState('')
  const [categorias, setCategorias] = useState([])
  const [categoriasEventoId, setCategoriasEventoId] = useState('')
  const [configuracion, setConfiguracion] = useState(null)
  const [cargandoEventos, setCargandoEventos] = useState(true)
  const [errorEventos, setErrorEventos] = useState('')
  const [errorCategorias, setErrorCategorias] = useState(null)
  const [errorConfiguracion, setErrorConfiguracion] = useState(null)
  const [reglamentoDisponible, setReglamentoDisponible] = useState(false)
  const [verificandoReglamento, setVerificandoReglamento] = useState(true)
  const [errorReglamento, setErrorReglamento] = useState('')
  const token = sessionStorage.getItem('uta.access_token')

  useEffect(() => {
    let activo = true
    cargarDatosInscripcion(token)
      .then((datos) => {
        if (!activo) return
        setEventos(datos.eventos)
        setEventoId(datos.eventos[0] ? String(datos.eventos[0].id) : '')
      })
      .catch((error) => activo && setErrorEventos(error.message || 'No se pudieron cargar los eventos.'))
      .finally(() => activo && setCargandoEventos(false))
    return () => { activo = false }
  }, [token])

  useEffect(() => {
    if (!eventoId) {
      return undefined
    }
    let activo = true

    cargarCategoriasEvento(eventoId)
      .then((datos) => {
        if (!activo) return
        setCategorias(datos)
        setCategoriasEventoId(eventoId)
      })
      .catch((error) => activo && setErrorCategorias({
        eventId: eventoId,
        message: error.message || 'No se pudieron cargar las categorías del evento.',
      }))

    cargarConfiguracionEvento(eventoId)
      .then((datos) => activo && setConfiguracion(datos))
      .catch((error) => activo && setErrorConfiguracion({
        eventId: eventoId,
        message: error.message || 'No se pudo cargar la configuración de tarifas.',
      }))
    return () => { activo = false }
  }, [eventoId])

  useEffect(() => {
    let activo = true
    fetch(REGLAMENTO_URL, { method: 'HEAD' })
      .then((response) => {
        const esPdf = response.ok && response.headers.get('content-type')?.includes('application/pdf')
        if (activo) setReglamentoDisponible(Boolean(esPdf))
      })
      .catch(() => {
        if (activo) setErrorReglamento('No se pudo verificar el archivo del reglamento.')
      })
      .finally(() => activo && setVerificandoReglamento(false))
    return () => { activo = false }
  }, [])

  const eventoSeleccionado = eventos.find((evento) => String(evento.id) === eventoId)
  const configuracionEvento = configuracion?.event_id === Number(eventoId) ? configuracion : null
  const categoriasEvento = categoriasEventoId === eventoId ? categorias : []
  const errorCategoriasEvento = errorCategorias?.eventId === eventoId ? errorCategorias.message : ''
  const errorConfiguracionEvento = errorConfiguracion?.eventId === eventoId ? errorConfiguracion.message : ''
  const cargandoCategorias = Boolean(eventoId) && categoriasEventoId !== eventoId && !errorCategoriasEvento

  function panelSeccion() {
    if (seccion === 'inicio') {
      return <BienvenidaParticipante user={user} onNavigate={setSeccion} />
    }
    if (seccion === 'inscripcion') return <Inscripcion />
    if (seccion === 'ordenes') {
      return <MisOrdenes token={token} onCrearInscripcion={() => setSeccion('inscripcion')} />
    }
    if (seccion === 'categorias') {
      return (
        <section className="participant-dashboard-panel">
          <header className="participant-panel-heading">
            <p className="participant-dashboard-eyebrow">COMPETENCIA</p>
            <h2>Categorías disponibles</h2>
            <p>Explora las categorías, conoce sus requisitos y encuentra la opción ideal para tu equipo.</p>
          </header>
          <label className="participant-event-select" htmlFor="participant-event">
            <span>Selecciona tu evento</span>
            <select id="participant-event" value={eventoId} onChange={(event) => setEventoId(event.target.value)} disabled={!eventos.length}>
              {!eventos.length && <option value="">No hay eventos disponibles</option>}
              {eventos.map((evento) => <option key={evento.id} value={evento.id}>{evento.name} {evento.edition_year}</option>)}
            </select>
          </label>
          {cargandoEventos && <p className="participant-dashboard-message">Cargando eventos...</p>}
          {errorEventos && <p className="participant-dashboard-error" role="alert">{errorEventos}</p>}
          {cargandoCategorias && <p className="participant-dashboard-message">Cargando categorías...</p>}
          {errorCategoriasEvento && <p className="participant-dashboard-error" role="alert">{errorCategoriasEvento}</p>}
          {errorConfiguracionEvento && <p className="participant-dashboard-error" role="alert">{errorConfiguracionEvento}</p>}
          {!cargandoCategorias && !errorCategoriasEvento && eventoId && categoriasEvento.length === 0 && (
            <div className="participant-category-empty">
              <span aria-hidden="true">🏁</span>
              <h3>Aún no hay categorías disponibles</h3>
              <p>Estamos preparando las categorías para este evento. Vuelve a consultar más adelante.</p>
            </div>
          )}
          {configuracionEvento && (
            <div className="participant-category-event-banner">
              <span className="participant-category-event-icon" aria-hidden="true">🏆</span>
              <div className="participant-category-event-info">
                <span>EVENTO SELECCIONADO</span>
                <strong>{eventoSeleccionado?.name} {eventoSeleccionado?.edition_year}</strong>
              </div>
              <p className={`participant-event-status ${configuracionEvento.registration_open && configuracionEvento.is_enabled ? 'is-open' : ''}`}>
                <span aria-hidden="true">{configuracionEvento.registration_open && configuracionEvento.is_enabled ? '●' : '○'}</span>
                Inscripciones {configuracionEvento.registration_open && configuracionEvento.is_enabled ? 'abiertas' : 'cerradas'}
              </p>
            </div>
          )}
          {eventoSeleccionado && categoriasEvento.length > 0 && (
            <div className="participant-category-grid">
              {categoriasEvento.map((categoria) => {
                const tarifa = configuracionEvento?.tariffs?.find(
                  (item) => item.category_id === categoria.category_id,
                )
                return (
                  <article className="participant-category-card" key={categoria.category_id}>
                    <div className="participant-category-card-top">
                      <span className="participant-category-icon" aria-hidden="true">🤖</span>
                      {categoria.is_active && <span className="participant-category-active">Disponible</span>}
                    </div>
                    <h3>{categoria.category_name}</h3>
                    <p className="participant-category-description">{categoria.description || 'Una categoría para poner a prueba la estrategia, el diseño y el control de tu robot.'}</p>
                    <div className="participant-category-price">
                      <span>Inscripción por equipo</span>
                      <strong>{tarifa ? `${configuracionEvento.currency || 'USD'} ${Number(tarifa.amount).toFixed(2)}` : 'Tarifa por confirmar'}</strong>
                    </div>
                    <h4>Requisitos de participación</h4>
                    <dl className="participant-category-rules">
                      <div>
                        <dt><span aria-hidden="true">👥</span> Participantes</dt>
                        <dd>{rango(categoria.min_participants, categoria.max_participants)}</dd>
                      </div>
                      <div>
                        <dt><span aria-hidden="true">🎓</span> Coaches</dt>
                        <dd>{rango(categoria.min_coaches, categoria.max_coaches)}</dd>
                      </div>
                      <div>
                        <dt><span aria-hidden="true">🎟️</span> Cupos</dt>
                        <dd>{categoria.max_registrations ?? 'Sin límite indicado'}</dd>
                      </div>
                    </dl>
                    <button className="participant-category-cta" type="button" onClick={() => setSeccion('inscripcion')}>
                      Inscribir mi equipo <span aria-hidden="true">→</span>
                    </button>
                  </article>
                )
              })}
            </div>
          )}
        </section>
      )
    }
    if (seccion === 'reglamento') {
      return (
        <section className="participant-dashboard-panel">
          <header className="participant-panel-heading">
            <p className="participant-dashboard-eyebrow">DOCUMENTACIÓN</p>
            <h2>Reglamento oficial</h2>
            <p>Consulta las reglas vigentes antes de completar la inscripción de tu equipo.</p>
          </header>
          {verificandoReglamento && <p className="participant-dashboard-message">Verificando el documento...</p>}
          {errorReglamento && <p className="participant-dashboard-error" role="alert">{errorReglamento}</p>}
          {!verificandoReglamento && reglamentoDisponible && (
            <>
              <a className="participant-document-link" href={REGLAMENTO_URL} target="_blank" rel="noreferrer">Abrir o descargar reglamento (PDF)</a>
              <iframe className="participant-regulation-viewer" src={REGLAMENTO_URL} title="Reglamento oficial de la competencia" />
            </>
          )}
          {!verificandoReglamento && !reglamentoDisponible && !errorReglamento && (
            <div className="participant-info-card">
              <h3>Documento pendiente de publicar</h3>
              <p>Guarda tu PDF como <strong>reglamento-oficial.pdf</strong> dentro de la carpeta <code>frontend/uta-sumo-web/public/</code>. El panel lo mostrará automáticamente en esta sección.</p>
              <p>Si me compartes el archivo, puedo dejarlo integrado en esa ubicación.</p>
            </div>
          )}
        </section>
      )
    }
    return (
      <section className="participant-dashboard-panel">
        <header className="participant-panel-heading">
          <p className="participant-dashboard-eyebrow">DATOS DE INSCRIPCIÓN</p>
          <h2>Información del equipo</h2>
          <p>Estos son los datos que se solicitan y registran en el formulario actual.</p>
        </header>
        <div className="participant-team-grid">
          <article className="participant-info-card">
            <h3>Equipo y robot</h3>
            <dl className="participant-category-rules">
              <div><dt>Nombre del equipo</dt><dd>Obligatorio; máximo 30 caracteres.</dd></div>
              <div><dt>Institución</dt><dd>Se toma de la cuenta del participante.</dd></div>
              <div><dt>Teléfono de contacto</dt><dd>Se toma del perfil cuando está disponible.</dd></div>
              <div><dt>Nombre del robot</dt><dd>Obligatorio; máximo 30 caracteres.</dd></div>
            </dl>
          </article>
          <article className="participant-info-card">
            <h3>Integrantes del equipo</h3>
            <p>El formulario vigente solicita dos participantes y un coach.</p>
            <ul className="participant-team-fields">
              <li>Nombres y apellidos (máximo 30 caracteres cada campo).</li>
              <li>Institución de cada integrante.</li>
              <li>Número celular de 10 dígitos.</li>
              <li>Rol: Participante 1, Participante 2 o Coach.</li>
            </ul>
          </article>
        </div>
        <button className="participant-dashboard-primary" type="button" onClick={() => setSeccion('inscripcion')}>
          Ir a Inscribir mi Robot
        </button>
      </section>
    )
  }

  return (
    <main className="participant-dashboard">
      <header className="participant-dashboard-header">
        <p className="participant-dashboard-eyebrow">CUENTA DE PARTICIPANTE</p>
        <h1>Hola{user?.first_name ? `, ${user.first_name}` : ''}</h1>
        <p>Administra tu inscripción, consulta tus órdenes y revisa la información de la competencia.</p>
      </header>
      <nav className="participant-dashboard-nav" role="tablist" aria-label="Secciones del panel de participante">
        {SECCIONES.map((item) => (
          <button
            key={item.id}
            id={`participant-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={seccion === item.id}
            aria-controls="participant-panel-content"
            onClick={() => setSeccion(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div
        className="participant-dashboard-content"
        id="participant-panel-content"
        role="tabpanel"
        aria-labelledby={`participant-tab-${seccion}`}
      >
        {panelSeccion()}
      </div>
    </main>
  )
}
