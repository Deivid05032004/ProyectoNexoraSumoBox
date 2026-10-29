import { useCallback, useEffect, useState } from 'react';
import { apiRequest } from './services/adminApi';
import './InstitutionsManagement.css';

const MAX_NAME_LENGTH = 150;

function ordenarInstituciones(items) {
  return [...items].sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'es', { sensitivity: 'base' }));
}

export default function InstitutionsManagement() {
  const [instituciones, setInstituciones] = useState([]);
  const [nombre, setNombre] = useState('');
  const [editandoId, setEditandoId] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');
  const [mensaje, setMensaje] = useState('');

  const cargarInstituciones = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const response = await apiRequest('/api/v1/institutions?page=1&limit=100');
      setInstituciones(ordenarInstituciones(Array.isArray(response) ? response : response?.items || []));
    } catch (reason) {
      setError(reason.message || 'No se pudieron cargar las instituciones.');
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargarInstituciones();
  }, [cargarInstituciones]);

  function limpiarFormulario() {
    setNombre('');
    setEditandoId(null);
  }

  function editarInstitucion(institucion) {
    setEditandoId(institucion.id);
    setNombre(institucion.name || '');
    setMensaje('');
    setError('');
  }

  async function guardarInstitucion(event) {
    event.preventDefault();
    const nombreNormalizado = nombre.trim();
    if (!nombreNormalizado) {
      setError('Escribe el nombre de la institución.');
      return;
    }
    if (nombreNormalizado.length > MAX_NAME_LENGTH) {
      setError(`El nombre no puede superar los ${MAX_NAME_LENGTH} caracteres.`);
      return;
    }

    setGuardando(true);
    setError('');
    setMensaje('');
    try {
      const response = await apiRequest(
        editandoId ? `/api/v1/institutions/${editandoId}` : '/api/v1/institutions',
        { method: editandoId ? 'PUT' : 'POST', body: JSON.stringify({ name: nombreNormalizado }) },
      );
      setInstituciones((actuales) => ordenarInstituciones(
        editandoId
          ? actuales.map((item) => Number(item.id) === Number(editandoId) ? response : item)
          : [...actuales, response],
      ));
      setMensaje(editandoId ? 'Institución actualizada correctamente.' : 'Institución agregada correctamente.');
      limpiarFormulario();
    } catch (reason) {
      setError(reason.message || 'No se pudo guardar la institución.');
    } finally {
      setGuardando(false);
    }
  }

  return (
    <section className="institutions-management" aria-labelledby="institutions-management-title">
      <div className="institutions-intro">
        <div>
          <span className="institutions-eyebrow">CATÁLOGO COMPARTIDO</span>
          <h2 id="institutions-management-title">Instituciones participantes</h2>
          <p>Administra los nombres que aparecerán en el acceso de participantes y en los campos de inscripción.</p>
        </div>
        <button type="button" className="institutions-refresh" onClick={() => void cargarInstituciones()} disabled={cargando || guardando}>
          {cargando ? 'Actualizando…' : 'Actualizar lista'}
        </button>
      </div>

      <form className="institution-editor" onSubmit={guardarInstitucion}>
        <label htmlFor="institution-name">Nombre de la institución
          <input id="institution-name" value={nombre} maxLength={MAX_NAME_LENGTH}
            onChange={(event) => { setNombre(event.target.value); setError(''); setMensaje(''); }}
            placeholder="Ej.: Universidad Técnica de Ambato" autoComplete="organization" />
        </label>
        <div className="institution-editor-actions">
          <button type="submit" className="institution-primary" disabled={guardando}>
            {guardando ? 'Guardando…' : editandoId ? 'Guardar cambios' : 'Agregar institución'}
          </button>
          {editandoId && <button type="button" className="institution-secondary" onClick={limpiarFormulario} disabled={guardando}>Cancelar edición</button>}
        </div>
      </form>

      {error && <p className="institution-feedback institution-feedback-error" role="alert">{error}</p>}
      {mensaje && <p className="institution-feedback institution-feedback-success" role="status">{mensaje}</p>}

      <div className="institution-list" aria-live="polite">
        <div className="institution-list-heading"><strong>Instituciones activas</strong><span>{instituciones.length} registradas</span></div>
        {cargando ? <p className="institution-empty">Cargando instituciones…</p>
          : !instituciones.length ? <p className="institution-empty">Todavía no hay instituciones activas.</p>
            : <ul>{instituciones.map((institucion) => <li key={institucion.id}>
              <span>{institucion.name}</span>
              <button type="button" onClick={() => editarInstitucion(institucion)}>Editar</button>
            </li>)}</ul>}
      </div>
      <p className="institution-note">Los cambios se reflejan al actualizar el acceso de participantes y el formulario de inscripción, porque ambos consultan este mismo catálogo.</p>
    </section>
  );
}
