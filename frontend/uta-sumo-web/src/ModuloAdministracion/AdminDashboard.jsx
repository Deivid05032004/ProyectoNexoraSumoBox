import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminWebSocketUrl, apiRequest, clearAdminSession, getAdminUser } from './services/adminApi';
import { obtenerInscripciones, actualizarEstadoInscripcion, actualizarEstadoPago, obtenerComprobante, exportarInscripcionesCSV } from './services/adminInscripcionesApi';
import TournamentManager from './components/TournamentManager';
import AdminCreateForm from './AdminCreateForm';
import RegistrationFormBuilder from './RegistrationFormBuilder';
import EventManagement from './EventManagement';
import AdminPasswordSettings from './AdminPasswordSettings';
import NavIcon from '../components/NavIcon';
import './AdminDashboard.css';

const STATUS_CHOICES = [
  ['PENDING', 'Pendiente'], ['APPROVED', 'Aprobado'], ['OBSERVED', 'Observado'], ['REJECTED', 'Rechazado'],
];
const FILTER_STATUS_CHOICES = [
  ['PAYMENT_PENDING', 'Pago pendiente'], ['PAYMENT_REVIEW', 'Pago en revisión'], ...STATUS_CHOICES,
];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [user] = useState(getAdminUser);
  const [activeSection, setActiveSection] = useState(() => getAdminUser()?.must_change_password ? 'security' : 'registrations');
  const eventoSeleccionadoRef = useRef(null);
  const [inscripciones, setInscripciones] = useState([]);
  const [eventos, setEventos] = useState([]);
  const [eventoSeleccionado, setEventoSeleccionado] = useState(null);
  const [eventPage, setEventPage] = useState(1);
  const [eventPageInfo, setEventPageInfo] = useState({ total: 0, total_pages: 0 });
  const [registrationPage, setRegistrationPage] = useState(1);
  const [registrationPageInfo, setRegistrationPageInfo] = useState({ total: 0, total_pages: 0 });
  const [categoryPage, setCategoryPage] = useState(1);
  const [categoryPageInfo, setCategoryPageInfo] = useState({ total: 0, total_pages: 0 });
  const [categorias, setCategorias] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [busquedaInstitucion, setBusquedaInstitucion] = useState('');
  const [filtroCategoria, setFiltroCategoria] = useState('');
  const [filtroEstado, setFiltroEstado] = useState('');
  const [modalResultadosAbierto, setModalResultadosAbierto] = useState(false);
  const [crearAdmin, setCrearAdmin] = useState(false);
  const [crearFormulario, setCrearFormulario] = useState(false);
  const [gestionarEventos, setGestionarEventos] = useState(false);
  const [actualizando, setActualizando] = useState(null);
  const [combateActual, setCombateActual] = useState(null);
  const [comprobante, setComprobante] = useState(null);
  const [cargandoComprobante, setCargandoComprobante] = useState(false);
  const [errorComprobante, setErrorComprobante] = useState('');
  const [motivoRechazo, setMotivoRechazo] = useState('');
  const [pagosEnVivo, setPagosEnVivo] = useState('connecting');

  const cargarEventos = useCallback(async () => {
    if (user?.must_change_password) return;
    try {
      const data = await apiRequest(`/api/v1/admin/events?active_only=true&page=${eventPage}&limit=5`);
      const items = data.items || [];
      setEventos(items);
      setEventPageInfo(data);
      if (!eventoSeleccionadoRef.current && items.length) {
        const initial = items.find((item) => ['LIVE', 'SCHEDULED'].includes(item.status)) || items[0];
        eventoSeleccionadoRef.current = initial;
        setEventoSeleccionado(initial);
      } else if (eventoSeleccionadoRef.current) {
        const refreshed = items.find((item) => Number(item.id) === Number(eventoSeleccionadoRef.current.id));
        if (refreshed) {
          eventoSeleccionadoRef.current = refreshed;
          setEventoSeleccionado(refreshed);
        }
      }
    } catch (err) {
      setError(err.message || 'No se pudieron cargar los eventos.');
      setCargando(false);
    }
  }, [eventPage, user]);

  useEffect(() => {
    const url = comprobante?.url;
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [comprobante?.url]);

  const cargar = useCallback(async ({ silencioso = false } = {}) => {
    if (user?.must_change_password) return;
    if (!silencioso) setCargando(true);
    if (!silencioso) setError('');
    if (!eventoSeleccionado) {
      setInscripciones([]);
      setCategorias([]);
      setRegistrationPageInfo({ total: 0, total_pages: 0 });
      if (!silencioso) setCargando(false);
      return;
    }
    try {
      const [rows, cats] = await Promise.all([
        obtenerInscripciones({ eventId: eventoSeleccionado.id, categoria: filtroCategoria, estado: filtroEstado, page: registrationPage }),
        apiRequest(`/api/v1/admin/events/${eventoSeleccionado.id}/categories?page=${categoryPage}&limit=5`),
      ]);
      setInscripciones(rows.items || []);
      setRegistrationPageInfo(rows);
      setCategorias(cats.items || []);
      setCategoryPageInfo(cats);
    } catch (err) {
      if (!silencioso) setError(err.message || 'Error al consultar las inscripciones.');
    } finally { if (!silencioso) setCargando(false); }
  }, [eventoSeleccionado, filtroCategoria, filtroEstado, registrationPage, categoryPage, user]);

  const cargarRef = useRef(cargar);
  useEffect(() => { cargarRef.current = cargar; }, [cargar]);

  useEffect(() => {
    if (!user || !['ADMIN', 'EVENT_MANAGER'].includes(user.role)) {
      navigate('/admin', { replace: true });
    }
  }, [user, navigate]);

  useEffect(() => {
    if (user?.role !== 'ADMIN' || user?.must_change_password) return undefined;
    const timer = window.setTimeout(() => cargarEventos(), 0);
    return () => window.clearTimeout(timer);
  }, [user, cargarEventos]);

  useEffect(() => {
    if (!eventoSeleccionado) return undefined;
    const timer = window.setTimeout(() => cargar(), 0);
    return () => window.clearTimeout(timer);
  }, [eventoSeleccionado, registrationPage, categoryPage, filtroCategoria, filtroEstado, cargar]);

  useEffect(() => {
    if (user?.role !== 'ADMIN' || user?.must_change_password) return undefined;
    let detenido = false;
    let socket;
    let temporizadorReconexion;
    let demoraReconexion = 1000;
    const token = sessionStorage.getItem('uta.access_token');

    function conectar() {
      if (detenido || !token) return;
      setPagosEnVivo('connecting');
      try {
        socket = new WebSocket(adminWebSocketUrl('/api/v1/payments/ws/admin'), [
          'uta-payment-updates', token,
        ]);
      } catch {
        setPagosEnVivo('offline');
        temporizadorReconexion = window.setTimeout(conectar, demoraReconexion);
        demoraReconexion = Math.min(demoraReconexion * 2, 30000);
        return;
      }
      socket.onopen = () => {
        demoraReconexion = 1000;
        setPagosEnVivo('online');
        // Reload immediately after subscription to close the REST/WS race window.
        void cargarRef.current({ silencioso: true });
      };
      socket.onmessage = ({ data }) => {
        let update;
        try { update = JSON.parse(data); } catch { return; }
        if (!['payment.receipt_submitted', 'payment.reviewed',
          'registration.created', 'registration.updated'].includes(update.type)) return;
        void cargarRef.current({ silencioso: true });
        if (['payment.receipt_submitted', 'registration.created'].includes(update.type)) {
          setToast(update.type === 'registration.created'
            ? 'Se registró un equipo nuevo. La lista de inscripciones se actualizó.'
            : 'Llegó un comprobante nuevo. La lista de inscripciones se actualizó.');
          window.setTimeout(() => setToast(''), 4500);
        }
      };
      socket.onclose = () => {
        if (detenido) return;
        setPagosEnVivo('offline');
        temporizadorReconexion = window.setTimeout(conectar, demoraReconexion);
        demoraReconexion = Math.min(demoraReconexion * 2, 30000);
      };
      socket.onerror = () => socket?.close();
    }

    conectar();
    // SQL changes made outside this API do not emit WebSocket events; periodic
    // reconciliation keeps the dashboard current even for those changes.
    const respaldo = window.setInterval(() => {
      void cargarRef.current({ silencioso: true });
    }, 30000);
    return () => {
      detenido = true;
      window.clearInterval(respaldo);
      window.clearTimeout(temporizadorReconexion);
      socket?.close();
    };
  }, [user]);

  useEffect(() => {
    let mounted = true;
    const consultarCombate = async () => {
      try {
        const snapshot = await apiRequest('/api/v1/competition/combate-actual');
        if (mounted) setCombateActual(snapshot?.active ? snapshot : null);
      } catch { if (mounted) setCombateActual(null); }
    };
    consultarCombate();
    const interval = window.setInterval(consultarCombate, 2500);
    return () => { mounted = false; window.clearInterval(interval); };
  }, []);

  function estaEnCombate(item) {
    const row = item.raw || {};
    return Boolean(combateActual && ['EN_VIVO', 'PAUSADO'].includes(combateActual.estado_code)
      && Number(row.event_id) === Number(combateActual.event_id)
      && Number(row.category_id) === Number(combateActual.category_id)
      && ((Number(row.team_id) === Number(combateActual.team_id_a) && Number(row.robot_id) === Number(combateActual.robot_id_a))
        || (Number(row.team_id) === Number(combateActual.team_id_b) && Number(row.robot_id) === Number(combateActual.robot_id_b))));
  }

  const visibles = useMemo(() => inscripciones.filter((item) =>
    !busquedaInstitucion.trim() || `${item.equipo} ${item.institucion} ${item.robot}`.toLowerCase().includes(busquedaInstitucion.toLowerCase())),
  [inscripciones, busquedaInstitucion]);

  const metricas = useMemo(() => ({
    total: visibles.length,
    pendientes: visibles.filter((item) => ['PENDING', 'PAYMENT_PENDING', 'PAYMENT_REVIEW'].includes(item.estado)
      || ['PENDING', 'IN_REVIEW'].includes(item.paymentStatus)).length,
    aprobadas: visibles.filter((item) => item.estado === 'APPROVED').length,
  }), [visibles]);

  async function cambiarEstado(item, status) {
    setActualizando(item.id);
    try {
      await actualizarEstadoInscripcion(item.id, status);
      setToast(`Inscripción ${item.codigo} actualizada: ${status}.`);
      await cargar();
    } catch (err) {
      setToast(`No se pudo actualizar: ${err.message}`);
    } finally {
      setActualizando(null);
      window.setTimeout(() => setToast(''), 4500);
    }
  }

  async function cambiarEstadoPago(item, status) {
    const key = `payment-${item.id}`;
    setActualizando(key);
    setErrorComprobante('');
    try {
      const payment = await actualizarEstadoPago(item.paymentId, status,
        status === 'REJECTED' ? motivoRechazo.trim() : 'Pago verificado tras revisar el comprobante.');
      const paymentStatusLabel = { PAID: 'Pagado', REJECTED: 'Rechazado' }[payment.status] || payment.status;
      const registrationLabels = {
        PAYMENT_PENDING: 'Pago pendiente', PAYMENT_REVIEW: 'Pago en revisión',
        PENDING: 'Pendiente', APPROVED: 'Aprobado', OBSERVED: 'Observado', REJECTED: 'Rechazado',
      };
      setInscripciones((rows) => rows.map((row) => row.id === item.id ? {
        ...row,
        paymentStatus: payment.status,
        paymentStatusLabel,
        hasReceipt: true,
        estado: payment.registration_status || row.estado,
        estadoLabel: registrationLabels[payment.registration_status] || row.estadoLabel,
        raw: { ...row.raw, payment_status: payment.status },
      } : row));
      setToast(`Pago de ${item.codigo}: ${paymentStatusLabel}.`);
      setComprobante(null);
      setMotivoRechazo('');
    } catch (err) {
      setToast(`No se pudo actualizar el pago: ${err.message}`);
      if (comprobante?.item.id === item.id) setErrorComprobante(err.message);
    } finally {
      setActualizando(null);
      window.setTimeout(() => setToast(''), 4500);
    }
  }

  async function abrirComprobante(item) {
    setComprobante({ item, url: null, mediaType: '' });
    setErrorComprobante('');
    setMotivoRechazo('');
    setCargandoComprobante(true);
    try {
      const blob = await obtenerComprobante(item.paymentId);
      setComprobante({ item, url: URL.createObjectURL(blob), mediaType: blob.type });
    } catch (err) {
      setErrorComprobante(err.message || 'No se pudo cargar el comprobante.');
    } finally {
      setCargandoComprobante(false);
    }
  }

  function cerrarSesion() {
    clearAdminSession();
    navigate('/admin', { replace: true });
  }

  return (
    <div className="admin-dashboard-page">
      <div className="admin-dashboard-shell">
        <aside className="admin-sidebar" aria-label="Navegación administrativa">
          <div className="admin-sidebar-brand">
            <span className="admin-sidebar-kicker">UTA SUMO 2026</span>
            <strong>Gestión del evento</strong>
          </div>
          <nav className="admin-sidebar-nav">
            {user?.role === 'ADMIN' && <button type="button" className={`admin-sidebar-link${activeSection === 'security' ? ' is-active' : ''}`} aria-current={activeSection === 'security' ? 'page' : undefined} onClick={() => setActiveSection('security')}>
              <span className="admin-sidebar-icon"><NavIcon name="security" /></span> Seguridad de la cuenta
            </button>}
            {!user?.must_change_password && <>
            <button type="button" className="admin-sidebar-link is-active" aria-current="page">
              <span className="admin-sidebar-icon"><NavIcon name="registration" /></span> Inscripciones
            </button>
            <button type="button" className="admin-sidebar-link" onClick={() => setModalResultadosAbierto(true)}>
              <span className="admin-sidebar-icon"><NavIcon name="competition" /></span> Grupos y marcador
            </button>
            {user?.role === 'ADMIN' && <button type="button" className="admin-sidebar-link" onClick={() => setCrearFormulario(true)}>
              <span className="admin-sidebar-icon"><NavIcon name="form" /></span> Formularios
            </button>}
            {user?.role === 'ADMIN' && <button type="button" className="admin-sidebar-link" onClick={() => setGestionarEventos(true)}>
              <span className="admin-sidebar-icon"><NavIcon name="competition" /></span> Eventos
            </button>}
            {user?.role === 'ADMIN' && <button type="button" className="admin-sidebar-link" onClick={() => setCrearAdmin(true)}>
              <span className="admin-sidebar-icon"><NavIcon name="staff" /></span> Personal autorizado
            </button>}
            </>}
          </nav>
          <div className="admin-sidebar-footer">
            <span className="admin-sidebar-user" title={user?.email}>{user?.email}</span>
            <button type="button" className="admin-sidebar-logout" onClick={cerrarSesion}><NavIcon name="logout" />Cerrar sesión</button>
          </div>
        </aside>
        {activeSection === 'security' ? <div className="admin-dashboard-container">
          <header className="admin-dashboard-header">
            <h1 className="admin-page-title">Seguridad de la cuenta</h1>
            <span className="admin-session-text">{user?.email}</span>
          </header>
          <AdminPasswordSettings required={Boolean(user?.must_change_password)} />
        </div> : <div className="admin-dashboard-container">
        <header className="admin-dashboard-header">
          <h1 className="admin-page-title">Inscripciones</h1>
          <div className="admin-header-actions">
            <span className="admin-session-text">{user?.role === 'ADMIN' ? 'Administrador' : 'Gestor de evento'}</span>
            {user?.role === 'ADMIN' && <span className={`admin-live-indicator ${pagosEnVivo === 'online' ? 'is-online' : ''}`} role="status">
              <span aria-hidden="true" />{pagosEnVivo === 'online' ? 'Inscripciones y pagos en vivo' : 'Reconectando actualizaciones…'}
            </span>}
            <button type="button" className="btn-admin-header" onClick={() => exportarInscripcionesCSV(visibles)}>Exportar página CSV</button>
          </div>
        </header>

        <section className="admin-event-selector" aria-label="Evento administrado">
          <div><span className="admin-event-kicker">CONTEXTO DE ADMINISTRACIÓN</span><label htmlFor="admin-event-select">Evento</label>
            <select id="admin-event-select" value={eventoSeleccionado?.id || ''} onChange={(event) => {
              const next = eventos.find((item) => String(item.id) === event.target.value);
              if (next) { eventoSeleccionadoRef.current = next; setEventoSeleccionado(next); setRegistrationPage(1); setCategoryPage(1); setFiltroCategoria(''); }
            }} disabled={!eventos.length}>
              {!eventos.length && <option value="">No hay eventos disponibles</option>}
              {eventoSeleccionado && !eventos.some((item) => Number(item.id) === Number(eventoSeleccionado.id))
                && <option value={eventoSeleccionado.id}>{eventoSeleccionado.name} · {eventoSeleccionado.edition_year}</option>}
              {eventos.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.edition_year} · {({ DRAFT: 'Borrador', SCHEDULED: 'Programado', LIVE: 'En curso', PAUSED: 'Pausado', FINISHED: 'Finalizado', CANCELLED: 'Cancelado' })[item.status] || item.status}</option>)}
            </select>
            <strong>{eventoSeleccionado ? `${eventoSeleccionado.name} · ${eventoSeleccionado.edition_year} · ${({ DRAFT: 'Borrador', SCHEDULED: 'Programado', LIVE: 'En curso', PAUSED: 'Pausado', FINISHED: 'Finalizado', CANCELLED: 'Cancelado' })[eventoSeleccionado.status] || eventoSeleccionado.status}` : 'Selecciona un evento para gestionar sus inscripciones y pagos'}</strong>
          </div>
          <div className="admin-pagination admin-event-pagination">
            <button type="button" disabled={eventPage <= 1} onClick={() => setEventPage((page) => Math.max(1, page - 1))}>Anterior</button>
            <span>Eventos activos · página {eventPage} de {Math.max(1, eventPageInfo.total_pages || 1)} · {eventPageInfo.total || 0} total</span>
            <button type="button" disabled={eventPage >= (eventPageInfo.total_pages || 1)} onClick={() => setEventPage((page) => page + 1)}>Siguiente</button>
          </div>
        </section>

        <section className="admin-summary-cards" aria-label="Resumen de inscripciones">
          <article className="summary-card"><div className="summary-number">{registrationPageInfo.total || 0}</div><div className="summary-label">Inscripciones del evento</div></article>
          <article className="summary-card"><div className="summary-number">{metricas.pendientes}</div><div className="summary-label">Pendientes en esta página</div></article>
          <article className="summary-card"><div className="summary-number">{metricas.aprobadas}</div><div className="summary-label">Aprobadas en esta página</div></article>
        </section>

        <section className="admin-filters-bar" aria-label="Filtros de búsqueda">
          <div className="filter-group filter-group-search"><label htmlFor="filter-institucion" className="filter-label">Buscar en esta página</label>
            <input id="filter-institucion" className="filter-input" value={busquedaInstitucion} onChange={(e) => setBusquedaInstitucion(e.target.value)} placeholder="Equipo, robot o institución" /></div>
          <div className="filter-group filter-group-select"><label htmlFor="filter-categoria" className="filter-label">Categoría</label>
            <select id="filter-categoria" className="filter-select" value={filtroCategoria} onChange={(e) => { setFiltroCategoria(e.target.value); setRegistrationPage(1); }}>
              <option value="">Todas</option>{categorias.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select></div>
          {categoryPageInfo.total_pages > 1 && <div className="admin-pagination admin-category-pagination">
            <button type="button" disabled={categoryPage <= 1} onClick={() => { setFiltroCategoria(''); setRegistrationPage(1); setCategoryPage((page) => Math.max(1, page - 1)); }}>‹</button>
            <span>Categorías {categoryPage} / {categoryPageInfo.total_pages}</span>
            <button type="button" disabled={categoryPage >= categoryPageInfo.total_pages} onClick={() => { setFiltroCategoria(''); setRegistrationPage(1); setCategoryPage((page) => page + 1); }}>›</button>
          </div>}
          <div className="filter-group filter-group-select"><label htmlFor="filter-estado" className="filter-label">Estado</label>
            <select id="filter-estado" className="filter-select" value={filtroEstado} onChange={(e) => { setFiltroEstado(e.target.value); setRegistrationPage(1); }}>
              <option value="">Todos</option>{FILTER_STATUS_CHOICES.map(([code, label]) => <option key={code} value={label}>{label}</option>)}
            </select></div>
        </section>

        {toast && <div className="table-state-box" role="status">{toast}</div>}
        <section className="admin-table-container">
          {cargando ? <div className="table-state-box">Cargando inscripciones del backend…</div>
            : error ? <div className="table-state-box table-error">{error}</div>
              : !visibles.length ? <div className="table-state-box">No se encontraron inscripciones.</div>
                : <table className="admin-table"><thead><tr><th>Equipo</th><th>Robot e institución</th><th>Integrantes</th><th>Tarifa</th><th>Estado de inscripción</th><th>Estado de pago</th><th>Comprobante</th></tr></thead>
                  <tbody>{visibles.map((item) => {
                    const bloqueadoPorCombate = estaEnCombate(item);
                    return <tr key={item.id} className="table-row">
                      <td className="cell-codigo" data-label="Equipo"><strong className="main-text">{item.equipo}</strong><span className="sub-text">Inscripción {item.codigo}</span><span className="sub-text">{item.fecha}</span></td>
                      <td className="cell-robot" data-label="Robot e institución"><strong className="main-text">{item.robot}</strong><span className="sub-text">{item.institucion}</span></td>
                      <td className="cell-integrantes" data-label="Integrantes"><div className="integrantes-list">{item.integrantes.map((person, index) => <div key={`${item.id}-${index}`} className="integrante-line"><span className="integrante-nombre">{person.nombre}</span><span className="integrante-celular">{person.celular}{person.esCoach ? ' · coach' : ''}</span></div>)}</div></td>
                      <td className="cell-tarifa" data-label="Tarifa"><span className="tarifa-amount">{item.tarifa} {item.raw.currency || ''}</span></td>
                      <td className="cell-estado" data-label="Estado de inscripción"><div className="estado-select-wrapper"><select className="estado-select" value={item.estado} disabled={bloqueadoPorCombate || item.estado === 'APPROVED' || actualizando === item.id}
                        onChange={(e) => cambiarEstado(item, e.target.value)} aria-label={`Cambiar estado de ${item.codigo}`}>
                        {STATUS_CHOICES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                      </select></div><span className="estado-subtext">{actualizando === item.id ? 'Guardando…' : bloqueadoPorCombate ? 'Bloqueado: en combate' : item.estado === 'APPROVED' ? 'Aprobado · bloqueado' : item.estadoLabel}</span></td>
                      <td className="cell-estado" data-label="Estado de pago"><strong className={`payment-status-badge status-${String(item.paymentStatus || 'none').toLowerCase()}`}>{item.paymentStatusLabel}</strong><span className="estado-subtext">{actualizando === `payment-${item.id}` ? 'Guardando…' : item.paymentStatus === 'PAID' ? 'Verificado' : item.paymentStatus === 'IN_REVIEW' ? 'Comprobante recibido' : item.paymentStatus === 'REJECTED' ? 'Requiere corrección' : item.paymentStatus === 'PENDING' ? 'Esperando envío del participante' : 'Sin pago registrado'}</span></td>
                      <td className="cell-comprobante" data-label="Comprobante">{item.hasReceipt ? <>
                        <button type="button" className="btn-review-receipt" disabled={!item.paymentId || actualizando === `payment-${item.id}`}
                          onClick={() => abrirComprobante(item)}>{item.paymentStatus === 'IN_REVIEW' ? 'Revisar comprobante' : 'Ver comprobante'}</button>
                        {item.receiptUploadedAt && <span className="estado-subtext">{new Date(item.receiptUploadedAt).toLocaleString()}</span>}
                      </> : <span className="estado-subtext">Aún no enviado</span>}</td>
                    </tr>;
                  })}</tbody></table>}
        </section>
        <div className="admin-pagination admin-registration-pagination">
          <span>Mostrando {visibles.length ? ((registrationPage - 1) * 5 + 1) : 0}–{Math.min((registrationPage - 1) * 5 + visibles.length, registrationPageInfo.total || 0)} de {registrationPageInfo.total || 0} inscripciones</span>
          <div><button type="button" disabled={registrationPage <= 1 || cargando} onClick={() => setRegistrationPage((page) => Math.max(1, page - 1))}>Anterior</button>
            <strong>Página {registrationPage} de {Math.max(1, registrationPageInfo.total_pages || 1)}</strong>
            <button type="button" disabled={registrationPage >= (registrationPageInfo.total_pages || 1) || cargando} onClick={() => setRegistrationPage((page) => page + 1)}>Siguiente</button></div>
        </div>
      </div>}
      </div>
      <TournamentManager isOpen={modalResultadosAbierto} event={eventoSeleccionado}
        onClose={() => setModalResultadosAbierto(false)} />
      {crearAdmin && <AdminCreateForm onClose={() => setCrearAdmin(false)} />}
      {crearFormulario && <RegistrationFormBuilder onClose={() => setCrearFormulario(false)} />}
      {gestionarEventos && <EventManagement onClose={() => setGestionarEventos(false)} />}
      {comprobante && <div className="receipt-modal-backdrop" role="presentation"
        onMouseDown={(event) => { if (event.target === event.currentTarget) setComprobante(null); }}>
        <section className="receipt-review-modal" role="dialog" aria-modal="true" aria-labelledby="receipt-review-title">
          <header className="receipt-review-header">
            <div><span className="receipt-review-eyebrow">VERIFICACIÓN DE PAGO</span>
              <h2 id="receipt-review-title">Comprobante · {comprobante.item.codigo}</h2>
              <p>{comprobante.item.robot} · {comprobante.item.tarifa} {comprobante.item.raw.currency || ''} · {comprobante.item.paymentStatusLabel}</p>
            </div>
            <button type="button" className="receipt-review-close" aria-label="Cerrar" onClick={() => setComprobante(null)}>×</button>
          </header>
          {cargandoComprobante && <div className="receipt-preview-state">Cargando comprobante seguro…</div>}
          {errorComprobante && <div className="receipt-preview-state receipt-preview-error" role="alert">{errorComprobante}</div>}
          {!cargandoComprobante && comprobante.url && (
            <div className="receipt-preview-frame">
              {comprobante.mediaType === 'application/pdf'
                ? <iframe src={comprobante.url} title={`Comprobante de pago ${comprobante.item.codigo}`} />
                : comprobante.mediaType?.startsWith('image/')
                  ? <img src={comprobante.url} alt={`Comprobante de pago ${comprobante.item.codigo}`} />
                  : <a href={comprobante.url} download={`comprobante-${comprobante.item.paymentId}`}>Descargar comprobante</a>}
            </div>
          )}
          {comprobante.item.paymentStatus === 'IN_REVIEW' && <>
            <label className="receipt-rejection-label" htmlFor="receipt-rejection-reason">Motivo (obligatorio al rechazar)</label>
            <textarea id="receipt-rejection-reason" value={motivoRechazo} maxLength={1000}
              onChange={(event) => setMotivoRechazo(event.target.value)} placeholder="Explica qué debe corregir el participante." />
          </>}
          <footer className="receipt-review-actions">
            <button type="button" className="btn-admin-header" onClick={() => setComprobante(null)}>Cerrar</button>
            {comprobante.item.paymentStatus === 'IN_REVIEW' && <>
              <button type="button" className="btn-reject-receipt"
                disabled={cargandoComprobante || !comprobante.url || !motivoRechazo.trim() || actualizando === `payment-${comprobante.item.id}`}
                onClick={() => cambiarEstadoPago(comprobante.item, 'REJECTED')}>Rechazar comprobante</button>
              <button type="button" className="btn-approve-payment"
                disabled={cargandoComprobante || !comprobante.url || actualizando === `payment-${comprobante.item.id}`}
                onClick={() => cambiarEstadoPago(comprobante.item, 'PAID')}>Confirmar pago</button>
            </>}
          </footer>
        </section>
      </div>}
    </div>
  );
}
