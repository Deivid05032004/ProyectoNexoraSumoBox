import { useEffect, useState } from 'react'
import BienvenidaParticipante from './BienvenidaParticipante'
import Inscripcion from './Inscripcion'
import MisOrdenes from './MisOrdenes'
import NavIcon from '../../components/NavIcon'
import {
  cargarCategoriasEvento,
  cargarConfiguracionEvento,
  cargarDatosInscripcion,
  cargarReglamentosEvento,
  urlApi,
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
function rango(minimo, maximo) {
  if (minimo == null && maximo == null) return 'No especificado'
  if (minimo != null && maximo != null) return `${minimo}–${maximo}`
  if (minimo != null) return `Mínimo ${minimo}`
  return `Máximo ${maximo}`
}

export default function ParticipantDashboard({ user }) {
  const [seccion, setSeccion] = useState('inicio')
  const [menuOpen, setMenuOpen] = useState(false)
  const [eventos, setEventos] = useState([])
  const [eventoId, setEventoId] = useState('')
  const [categorias, setCategorias] = useState([])
  const [categoriasEventoId, setCategoriasEventoId] = useState('')
  const [configuracion, setConfiguracion] = useState(null)
  const [cargandoEventos, setCargandoEventos] = useState(true)
  const [errorEventos, setErrorEventos] = useState('')
  const [errorCategorias, setErrorCategorias] = useState(null)
  const [errorConfiguracion, setErrorConfiguracion] = useState(null)
  const [reglamentoCategoriaId, setReglamentoCategoriaId] = useState('')
  const [reglamentos, setReglamentos] = useState([])
  const [reglamentoSeleccionadoId, setReglamentoSeleccionadoId] = useState(null)
  const [cargandoReglamento, setCargandoReglamento] = useState(false)
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
    if (!eventoId) {
      setReglamentos([])
      setCargandoReglamento(false)
      return undefined
    }
    let activo = true
    setCargandoReglamento(true)
    setErrorReglamento('')
    cargarReglamentosEvento(eventoId, reglamentoCategoriaId || null)
      .then((result) => {
        if (!activo) return
        const items = Array.isArray(result) ? result : []
        setReglamentos(items)
        setReglamentoSeleccionadoId(items[0]?.id ?? null)
      })
      .catch((error) => activo && setErrorReglamento(error.message || 'No se pudieron cargar los reglamentos.'))
      .finally(() => activo && setCargandoReglamento(false))
    return () => { activo = false }
  }, [eventoId, reglamentoCategoriaId])

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
      const regulation = reglamentos.find((item) => item.id === reglamentoSeleccionadoId)
      const fileUrl = regulation ? urlApi(regulation.download_url) : ''
      return (
        <section className="participant-dashboard-panel">
          <header className="participant-panel-heading">
            <p className="participant-dashboard-eyebrow">DOCUMENTACIÓN</p>
            <h2>Reglamento oficial</h2>
            <p>Consulta el documento vigente que administra el organizador para el evento y la categoría seleccionados.</p>
          </header>
          <label className="participant-event-select" htmlFor="participant-regulation-event">
            <span>Evento</span>
            <select id="participant-regulation-event" value={eventoId}
              onChange={(event) => { setEventoId(event.target.value); setReglamentoCategoriaId('') }}
              disabled={!eventos.length}>
              {!eventos.length && <option value="">No hay eventos disponibles</option>}
              {eventos.map((evento) => <option key={evento.id} value={evento.id}>{evento.name} {evento.edition_year}</option>)}
            </select>
          </label>
          <label className="participant-event-select" htmlFor="participant-regulation-category">
            <span>Categoría</span>
            <select id="participant-regulation-category" value={reglamentoCategoriaId}
              onChange={(event) => setReglamentoCategoriaId(event.target.value)}
              disabled={!eventoId || cargandoCategorias}>
              <option value="">Todos los reglamentos publicados</option>
              {categoriasEvento.map((categoria) => (
                <option key={categoria.category_id} value={categoria.category_id}>{categoria.category_name}</option>
              ))}
            </select>
          </label>
          {cargandoReglamento && <p className="participant-dashboard-message">Cargando reglamentos publicados...</p>}
          {errorReglamento && <p className="participant-dashboard-error" role="alert">{errorReglamento}</p>}
          {!cargandoReglamento && !errorReglamento && reglamentos.length > 0 && (
            <>
              <div className="participant-regulation-list">
                {reglamentos.map((item) => (
                  <article className="participant-info-card" key={item.id}>
                    <h3>{item.title}</h3>
                    <p>{item.event_name} · {item.category_name || 'Reglamento general del evento'} · Versión {item.version}</p>
                    <p>Vigente desde {item.effective_from}{item.effective_until ? ` hasta ${item.effective_until}` : ''}</p>
                    <button className="participant-document-link" type="button"
                      aria-pressed={item.id === reglamentoSeleccionadoId}
                      onClick={() => setReglamentoSeleccionadoId(item.id)}>
                      {item.id === reglamentoSeleccionadoId ? 'Documento seleccionado' : 'Ver este reglamento'}
                    </button>
                    <a className="participant-document-link participant-document-link-secondary"
                      href={urlApi(item.download_url)} target="_blank" rel="noreferrer">Abrir o descargar PDF</a>
                  </article>
                ))}
              </div>
              {regulation && <iframe className="participant-regulation-viewer" src={fileUrl} title={`Reglamento ${regulation.title}`} />}
            </>
          )}
          {!cargandoReglamento && !errorReglamento && reglamentos.length === 0 && (
            <div className="participant-info-card">
              <h3>Documento pendiente de publicar</h3>
              <p>El administrador aún no ha publicado un reglamento vigente para el evento o categoría seleccionados.</p>
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
        <div>
          <p className="participant-dashboard-eyebrow">CUENTA DE PARTICIPANTE</p>
          <h1>Hola{user?.first_name ? `, ${user.first_name}` : ''}</h1>
          <p>Administra tu inscripción, consulta tus órdenes y revisa la información de la competencia.</p>
        </div>
        <button className="participant-menu-toggle" type="button" aria-expanded={menuOpen}
          aria-controls="participant-dashboard-nav" onClick={() => setMenuOpen((open) => !open)}>
          <span aria-hidden="true">{menuOpen ? '×' : '☰'}</span>{menuOpen ? 'Cerrar menú' : 'Secciones'}
        </button>
      </header>
      <div className="participant-dashboard-layout">
        <aside className={`participant-dashboard-sidebar${menuOpen ? ' is-open' : ''}`}>
          <nav id="participant-dashboard-nav" className="participant-dashboard-nav"
            aria-label="Secciones del panel de participante">
            {SECCIONES.map((item) => (
              <button
                key={item.id}
                id={`participant-tab-${item.id}`}
                type="button"
                aria-current={seccion === item.id ? 'page' : undefined}
                aria-controls="participant-panel-content"
                onClick={() => { setSeccion(item.id); setMenuOpen(false) }}
              >
                <NavIcon name={{ inicio: 'home', inscripcion: 'registration', ordenes: 'orders', categorias: 'categories', reglamento: 'rules', equipo: 'team' }[item.id]} />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>
        </aside>
        <section
          className="participant-dashboard-content"
          id="participant-panel-content"
          aria-labelledby={`participant-tab-${seccion}`}
          aria-label={`Contenido: ${SECCIONES.find((item) => item.id === seccion)?.label || 'Panel'}`}
        >
          {panelSeccion()}
        </section>
      </div>
    </main>
  )
}
