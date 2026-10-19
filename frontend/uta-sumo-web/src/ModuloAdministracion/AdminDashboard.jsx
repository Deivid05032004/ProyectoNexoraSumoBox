import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  obtenerInscripciones,
  actualizarEstadoInscripcion,
  exportarInscripcionesCSV,
} from './services/adminInscripcionesApi';
import ResultadosModal from './components/ResultadosModal';
import './AdminDashboard.css';

export default function AdminDashboard() {
  const navigate = useNavigate();

  // Estado del revisor en sesión (inicializado perezosamente para React 19)
  const [usuarioActual] = useState(() => {
    try {
      const storedRevisor = sessionStorage.getItem('uta.revisor');
      if (storedRevisor) return storedRevisor;
      const storedUser = JSON.parse(sessionStorage.getItem('uta.user') || 'null');
      if (storedUser?.username) return storedUser.username;
    } catch {
      // fallback
    }
    return 'revisor1';
  });

  // Estados de datos preparados para backend (mock fetch)
  const [inscripciones, setInscripciones] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);

  // Estados de filtros
  const [busquedaInstitucion, setBusquedaInstitucion] = useState('');
  const [filtroCategoria, setFiltroCategoria] = useState('Todas');
  const [filtroEstado, setFiltroEstado] = useState('Todos');

  // Estado del modal de gestión de resultados en vivo
  const [modalResultadosAbierto, setModalResultadosAbierto] = useState(false);

  // Carga inicial simulando llamada a API asíncrona
  useEffect(() => {
    let activo = true;

    async function cargarInscripcionesApi() {
      try {
        setCargando(true);
        setError(null);
        // Función asíncrona: en el futuro solo cambiar la URL del fetch interno
        const datos = await obtenerInscripciones();
        if (activo) {
          setInscripciones(datos);
        }
      } catch (err) {
        if (activo) {
          setError(err.message || 'Error al consultar las inscripciones.');
        }
      } finally {
        if (activo) {
          setCargando(false);
        }
      }
    }

    cargarInscripcionesApi();

    return () => {
      activo = false;
    };
  }, []);

  // Manejo de cambio de estado (Pendiente / Aprobado)
  const handleCambiarEstado = async (id, nuevoEstado) => {
    try {
      // Llamada simulada a PATCH/PUT de backend
      const listaActualizada = await actualizarEstadoInscripcion(
        id,
        nuevoEstado,
        usuarioActual
      );
      setInscripciones(listaActualizada);
    } catch (err) {
      console.error('Error al actualizar estado:', err);
    }
  };

  // Manejo de cierre de sesión
  const handleCerrarSesion = () => {
    sessionStorage.removeItem('uta.access_token');
    sessionStorage.removeItem('uta.user');
    sessionStorage.removeItem('uta.revisor');
    sessionStorage.removeItem('uta.admin_session');
    window.dispatchEvent(new Event('uta-session-changed'));
    navigate('/admin', { replace: true });
  };

  // Cálculos dinámicos de las tarjetas de resumen
  const metricas = useMemo(() => {
    const total = inscripciones.length;
    const pendientes = inscripciones.filter((i) => i.estado === 'Pendiente').length;
    const aprobadas = inscripciones.filter((i) => i.estado === 'Aprobado').length;
    return { total, pendientes, aprobadas };
  }, [inscripciones]);

  // Filtrado reactivo de la tabla
  const inscripcionesFiltradas = useMemo(() => {
    return inscripciones.filter((item) => {
      // Filtro por institución o nombre de robot
      const coincideInstitucion =
        !busquedaInstitucion.trim() ||
        item.institucion.toLowerCase().includes(busquedaInstitucion.toLowerCase()) ||
        item.robot.toLowerCase().includes(busquedaInstitucion.toLowerCase());

      // Filtro por categoría
      const coincideCategoria =
        filtroCategoria === 'Todas' || item.categoria === filtroCategoria;

      // Filtro por estado
      const coincideEstado =
        filtroEstado === 'Todos' || item.estado === filtroEstado;

      return coincideInstitucion && coincideCategoria && coincideEstado;
    });
  }, [inscripciones, busquedaInstitucion, filtroCategoria, filtroEstado]);

  return (
    <div className="admin-dashboard-page">
      <div className="admin-dashboard-container">
        {/* HEADER SUPERIOR */}
        <header className="admin-dashboard-header">
          <h1 className="admin-page-title">Inscripciones</h1>

          <div className="admin-header-actions">
            <span className="admin-session-text">Sesión: {usuarioActual}</span>

            {/* Botón para gestión de marcadores en tiempo real (Req. 3) */}
            <button
              type="button"
              className="btn-admin-results"
              onClick={() => setModalResultadosAbierto(true)}
              title="Abrir panel de resultados en vivo"
            >
              <span className="live-dot" />
              Marcador en vivo
            </button>

            <button
              type="button"
              className="btn-admin-header"
              onClick={() => exportarInscripcionesCSV(inscripcionesFiltradas)}
            >
              Exportar CSV
            </button>

            <button
              type="button"
              className="btn-admin-header"
              onClick={handleCerrarSesion}
            >
              Cerrar sesión
            </button>
          </div>
        </header>

        {/* TARJETAS DE RESUMEN (Métricas) */}
        <section className="admin-summary-cards" aria-label="Resumen de inscripciones">
          <article className="summary-card">
            <div className="summary-number">{metricas.total}</div>
            <div className="summary-label">Total</div>
          </article>

          <article className="summary-card">
            <div className="summary-number">{metricas.pendientes}</div>
            <div className="summary-label">Pendientes</div>
          </article>

          <article className="summary-card">
            <div className="summary-number">{metricas.aprobadas}</div>
            <div className="summary-label">Aprobadas</div>
          </article>
        </section>

        {/* BARRA DE FILTROS */}
        <section className="admin-filters-bar" aria-label="Filtros de búsqueda">
          <div className="filter-group filter-group-search">
            <label htmlFor="filter-institucion" className="filter-label">
              Buscar por institución
            </label>
            <input
              id="filter-institucion"
              type="text"
              className="filter-input"
              value={busquedaInstitucion}
              onChange={(e) => setBusquedaInstitucion(e.target.value)}
              placeholder=""
            />
          </div>

          <div className="filter-group filter-group-select">
            <label htmlFor="filter-categoria" className="filter-label">
              Categoría
            </label>
            <select
              id="filter-categoria"
              className="filter-select"
              value={filtroCategoria}
              onChange={(e) => setFiltroCategoria(e.target.value)}
            >
              <option value="Todas">Todas</option>
              <option value="Mini Sumo RC Amateur">Mini Sumo RC Amateur</option>
            </select>
          </div>

          <div className="filter-group filter-group-select">
            <label htmlFor="filter-estado" className="filter-label">
              Estado
            </label>
            <select
              id="filter-estado"
              className="filter-select"
              value={filtroEstado}
              onChange={(e) => setFiltroEstado(e.target.value)}
            >
              <option value="Todos">Todos</option>
              <option value="Pendiente">Pendiente</option>
              <option value="Aprobado">Aprobado</option>
            </select>
          </div>
        </section>

        {/* TABLA DE DATOS */}
        <section className="admin-table-container">
          {cargando ? (
            <div className="table-state-box">Cargando inscripciones del torneo...</div>
          ) : error ? (
            <div className="table-state-box table-error">{error}</div>
          ) : inscripcionesFiltradas.length === 0 ? (
            <div className="table-state-box">No se encontraron inscripciones con los filtros seleccionados.</div>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th scope="col" style={{ width: '15%' }}>Código</th>
                  <th scope="col" style={{ width: '22%' }}>Robot e institución</th>
                  <th scope="col" style={{ width: '33%' }}>Integrantes</th>
                  <th scope="col" style={{ width: '12%' }}>Tarifa</th>
                  <th scope="col" style={{ width: '18%' }}>Estado</th>
                </tr>
              </thead>
              <tbody>
                {inscripcionesFiltradas.map((item) => (
                  <tr key={item.id} className="table-row">
                    {/* Código */}
                    <td className="cell-codigo">
                      <strong className="main-text">{item.codigo}</strong>
                      <span className="sub-text">{item.fecha}</span>
                    </td>

                    {/* Robot e institución */}
                    <td className="cell-robot">
                      <strong className="main-text">{item.robot}</strong>
                      <span className="sub-text">{item.institucion}</span>
                    </td>

                    {/* Integrantes */}
                    <td className="cell-integrantes">
                      <div className="integrantes-list">
                        {item.integrantes.map((m, idx) => (
                          <div key={idx} className="integrante-line">
                            <span className="integrante-nombre">{m.nombre}</span>
                            <span className="integrante-celular">
                              {m.celular}
                              {m.esCoach ? ' · coach' : ''}
                            </span>
                          </div>
                        ))}
                      </div>
                    </td>

                    {/* Tarifa */}
                    <td className="cell-tarifa">
                      <span className="tarifa-amount">${item.tarifa}</span>
                    </td>

                    {/* Estado con dropdown interactivo */}
                    <td className="cell-estado">
                      <div className="estado-select-wrapper">
                        <select
                          className={`estado-select ${item.estado.toLowerCase()}`}
                          value={item.estado}
                          onChange={(e) => handleCambiarEstado(item.id, e.target.value)}
                          aria-label={`Cambiar estado de ${item.codigo}`}
                        >
                          <option value="Aprobado">Aprobado</option>
                          <option value="Pendiente">Pendiente</option>
                        </select>
                      </div>
                      <span className="estado-subtext">
                        {item.estado === 'Aprobado'
                          ? `Revisó ${item.revisor || usuarioActual}`
                          : 'Sin revisar'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      {/* Modal exclusivo de administración para resultados en tiempo real */}
      <ResultadosModal
        isOpen={modalResultadosAbierto}
        onClose={() => setModalResultadosAbierto(false)}
      />
    </div>
  );
}
