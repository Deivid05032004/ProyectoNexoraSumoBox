import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiRequest, getAdminUser } from './services/adminApi';
import { obtenerInscripciones, actualizarEstadoInscripcion, actualizarEstadoPago, exportarInscripcionesCSV } from './services/adminInscripcionesApi';
import ResultadosModal from './components/ResultadosModal';
import AdminCreateForm from './AdminCreateForm';
import RegistrationFormBuilder from './RegistrationFormBuilder';
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
  const [inscripciones, setInscripciones] = useState([]);
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
  const [actualizando, setActualizando] = useState(null);
  const [combateActual, setCombateActual] = useState(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const [rows, cats] = await Promise.all([
        obtenerInscripciones({ categoria: filtroCategoria, estado: filtroEstado }),
        apiRequest('/api/v1/categories?page=1&limit=100'),
      ]);
      setInscripciones(rows);
      setCategorias(cats);
    } catch (err) {
      setError(err.message || 'Error al consultar las inscripciones.');
    } finally { setCargando(false); }
  }, [filtroCategoria, filtroEstado]);

  useEffect(() => {
    if (!user || !['ADMIN', 'EVENT_MANAGER'].includes(user.role)) {
      navigate('/admin', { replace: true });
      return;
    }
    cargar();
  }, [user, navigate, cargar]);

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
    !busquedaInstitucion.trim() || `${item.institucion} ${item.robot}`.toLowerCase().includes(busquedaInstitucion.toLowerCase())),
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
    try {
      const payment = await actualizarEstadoPago(item.paymentId, status);
      const paymentStatusLabel = { PAID: 'Pagado', REJECTED: 'Rechazado' }[payment.status] || payment.status;
      const registrationLabels = {
        PAYMENT_PENDING: 'Pago pendiente', PAYMENT_REVIEW: 'Pago en revisión',
        PENDING: 'Pendiente', APPROVED: 'Aprobado', OBSERVED: 'Observado', REJECTED: 'Rechazado',
      };
      setInscripciones((rows) => rows.map((row) => row.id === item.id ? {
        ...row,
        paymentStatus: payment.status,
        paymentStatusLabel,
        estado: payment.registration_status || row.estado,
        estadoLabel: registrationLabels[payment.registration_status] || row.estadoLabel,
        raw: { ...row.raw, payment_status: payment.status },
      } : row));
      setToast(`Pago de ${item.codigo}: ${paymentStatusLabel}.`);
    } catch (err) {
      setToast(`No se pudo actualizar el pago: ${err.message}`);
    } finally {
      setActualizando(null);
      window.setTimeout(() => setToast(''), 4500);
    }
  }

  function cerrarSesion() {
    ['uta.access_token', 'uta.user', 'uta.revisor'].forEach((key) => sessionStorage.removeItem(key));
    window.dispatchEvent(new Event('uta-session-changed'));
    navigate('/admin', { replace: true });
  }

  return (
    <div className="admin-dashboard-page">
      <div className="admin-dashboard-container">
        <header className="admin-dashboard-header">
          <h1 className="admin-page-title">Inscripciones</h1>
          <div className="admin-header-actions">
            <span className="admin-session-text">Sesión: {user?.email} · {user?.role}</span>
            <button type="button" className="btn-admin-results" onClick={() => setModalResultadosAbierto(true)}><span className="live-dot" /> Marcador en vivo</button>
            {user?.role === 'ADMIN' && <button type="button" className="btn-admin-header" onClick={() => setCrearFormulario(true)}>Crear formulario</button>}
            <button type="button" className="btn-admin-header" onClick={() => setCrearAdmin(true)}>Nuevo administrador</button>
            <button type="button" className="btn-admin-header" onClick={() => exportarInscripcionesCSV(visibles)}>Exportar CSV</button>
            <button type="button" className="btn-admin-header" onClick={cerrarSesion}>Cerrar sesión</button>
          </div>
        </header>

        <section className="admin-summary-cards" aria-label="Resumen de inscripciones">
          <article className="summary-card"><div className="summary-number">{metricas.total}</div><div className="summary-label">En esta página</div></article>
          <article className="summary-card"><div className="summary-number">{metricas.pendientes}</div><div className="summary-label">Pendientes</div></article>
          <article className="summary-card"><div className="summary-number">{metricas.aprobadas}</div><div className="summary-label">Aprobadas</div></article>
        </section>

        <section className="admin-filters-bar" aria-label="Filtros de búsqueda">
          <div className="filter-group filter-group-search"><label htmlFor="filter-institucion" className="filter-label">Buscar por institución</label>
            <input id="filter-institucion" className="filter-input" value={busquedaInstitucion} onChange={(e) => setBusquedaInstitucion(e.target.value)} placeholder="Institución o robot" /></div>
          <div className="filter-group filter-group-select"><label htmlFor="filter-categoria" className="filter-label">Categoría</label>
            <select id="filter-categoria" className="filter-select" value={filtroCategoria} onChange={(e) => setFiltroCategoria(e.target.value)}>
              <option value="">Todas</option>{categorias.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select></div>
          <div className="filter-group filter-group-select"><label htmlFor="filter-estado" className="filter-label">Estado</label>
            <select id="filter-estado" className="filter-select" value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)}>
              <option value="">Todos</option>{FILTER_STATUS_CHOICES.map(([code, label]) => <option key={code} value={label}>{label}</option>)}
            </select></div>
        </section>

        {toast && <div className="table-state-box" role="status">{toast}</div>}
        <section className="admin-table-container">
          {cargando ? <div className="table-state-box">Cargando inscripciones del backend…</div>
            : error ? <div className="table-state-box table-error">{error}</div>
              : !visibles.length ? <div className="table-state-box">No se encontraron inscripciones.</div>
                : <table className="admin-table"><thead><tr><th>Código</th><th>Robot e institución</th><th>Integrantes</th><th>Tarifa</th><th>Estado de inscripción</th><th>Estado de pago</th></tr></thead>
                  <tbody>{visibles.map((item) => {
                    const bloqueadoPorCombate = estaEnCombate(item);
                    return <tr key={item.id} className="table-row">
                      <td className="cell-codigo"><strong className="main-text">{item.codigo}</strong><span className="sub-text">{item.fecha}</span></td>
                      <td className="cell-robot"><strong className="main-text">{item.robot}</strong><span className="sub-text">{item.institucion}</span></td>
                      <td className="cell-integrantes"><div className="integrantes-list">{item.integrantes.map((person, index) => <div key={`${item.id}-${index}`} className="integrante-line"><span className="integrante-nombre">{person.nombre}</span><span className="integrante-celular">{person.celular}{person.esCoach ? ' · coach' : ''}</span></div>)}</div></td>
                      <td className="cell-tarifa"><span className="tarifa-amount">{item.tarifa} {item.raw.currency || ''}</span></td>
                      <td className="cell-estado"><div className="estado-select-wrapper"><select className="estado-select" value={item.estado} disabled={bloqueadoPorCombate || item.estado === 'APPROVED' || actualizando === item.id}
                        onChange={(e) => cambiarEstado(item, e.target.value)} aria-label={`Cambiar estado de ${item.codigo}`}>
                        {STATUS_CHOICES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                      </select></div><span className="estado-subtext">{actualizando === item.id ? 'Guardando…' : bloqueadoPorCombate ? 'Bloqueado: en combate' : item.estado === 'APPROVED' ? 'Aprobado · bloqueado' : item.estadoLabel}</span></td>
                      <td className="cell-estado"><div className="estado-select-wrapper"><select className="estado-select" value={item.paymentStatus || ''}
                        disabled={bloqueadoPorCombate || item.paymentStatus === 'PAID' || !item.paymentId || actualizando === `payment-${item.id}`}
                        onChange={(e) => cambiarEstadoPago(item, e.target.value)} aria-label={`Cambiar estado de pago de ${item.codigo}`}>
                        <option value={item.paymentStatus || ''}>{item.paymentStatusLabel}</option>
                        {item.paymentStatus !== 'PAID' && <option value="PAID">Pagado</option>}
                        {item.paymentStatus !== 'REJECTED' && <option value="REJECTED">Rechazado</option>}
                      </select></div><span className="estado-subtext">{actualizando === `payment-${item.id}` ? 'Guardando…' : bloqueadoPorCombate ? 'Bloqueado: en combate' : item.paymentStatus === 'PAID' ? 'Pagado · bloqueado' : item.paymentStatusLabel}</span></td>
                    </tr>;
                  })}</tbody></table>}
        </section>
      </div>
      <ResultadosModal isOpen={modalResultadosAbierto} onClose={() => setModalResultadosAbierto(false)} />
      {crearAdmin && <AdminCreateForm onClose={() => setCrearAdmin(false)} />}
      {crearFormulario && <RegistrationFormBuilder onClose={() => setCrearFormulario(false)} />}
    </div>
  );
}
