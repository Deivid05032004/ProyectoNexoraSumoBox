import { useCallback, useEffect, useState } from 'react';
import { apiRequest, apiRequestPage } from '../services/adminApi';
import './GroupManagement.css';

const emptyGroup = { name: '', code: '', max_teams: '' };

export default function GroupManagement({ isOpen, event, onClose, embedded = false, selectedCategoryId, onStateChange }) {
  const [categories, setCategories] = useState([]);
  const [categoryId, setCategoryId] = useState('');
  const [groups, setGroups] = useState([]);
  const [eligible, setEligible] = useState([]);
  const [eligiblePage, setEligiblePage] = useState(1);
  const [eligibleInfo, setEligibleInfo] = useState({ total: 0, total_pages: 0 });
  const [groupForm, setGroupForm] = useState(emptyGroup);
  const [editingGroupId, setEditingGroupId] = useState(null);
  const [selectionByGroup, setSelectionByGroup] = useState({});
  const [moveTargets, setMoveTargets] = useState({});
  const [locked, setLocked] = useState(false);
  const [lockReason, setLockReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const basePath = `/api/v1/admin/events/${event?.id}/categories/${categoryId}/tournament-groups`;

  const loadGroups = useCallback(async () => {
    if (!isOpen || !event?.id || !categoryId) {
      setGroups([]);
      return;
    }
    const [result, registrationsPage] = await Promise.all([
      apiRequest(basePath),
      apiRequestPage(`${basePath}/eligible-registrations?page=${eligiblePage}&limit=5`),
    ]);
    setGroups(result.groups || []);
    setLocked(Boolean(result.locked));
    setLockReason(result.lock_reason || '');
    setEligible(registrationsPage.data?.items || []);
    setEligibleInfo({ total: registrationsPage.total, total_pages: registrationsPage.totalPages });
    onStateChange?.({ groups: result.groups || [], locked: Boolean(result.locked) });
  }, [basePath, categoryId, eligiblePage, event?.id, isOpen, onStateChange]);

  useEffect(() => {
    if (!isOpen || !event?.id) return undefined;
    let active = true;
    setLoading(true);
    setError('');
    apiRequest(`/api/v1/events/${event.id}/categories?page=1&limit=100`)
      .then((rows) => {
        if (!active) return;
        const available = (Array.isArray(rows) ? rows : []).filter((item) => item.is_active);
        setCategories(available);
        setCategoryId((current) => available.some((item) => String(item.category_id) === current)
          ? current : String(available[0]?.category_id || ''));
      })
      .catch((err) => active && setError(err.message || 'No se pudieron cargar las categorías del evento.'))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [isOpen, event?.id]);

  useEffect(() => {
    if (selectedCategoryId && String(selectedCategoryId) !== categoryId) {
      setCategoryId(String(selectedCategoryId));
      setEligiblePage(1);
      resetForm();
    }
  }, [selectedCategoryId]);

  useEffect(() => {
    let active = true;
    if (!isOpen || !categoryId) return undefined;
    setLoading(true);
    setError('');
    loadGroups()
      .catch((err) => active && setError(err.message || 'No se pudieron cargar los grupos.'))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [isOpen, categoryId, eligiblePage, loadGroups]);

  function resetForm() {
    setGroupForm(emptyGroup);
    setEditingGroupId(null);
  }

  async function saveGroup(eventForm) {
    eventForm.preventDefault();
    setSaving(true); setError(''); setNotice('');
    try {
      const path = editingGroupId ? `${basePath}/${editingGroupId}` : basePath;
      const result = await apiRequest(path, {
        method: editingGroupId ? 'PATCH' : 'POST',
        body: JSON.stringify({ ...groupForm, max_teams: Number(groupForm.max_teams) }),
      });
      resetForm();
      setNotice(editingGroupId ? 'Grupo actualizado.' : 'Grupo creado.');
      await loadGroups();
      if (!editingGroupId) setEligiblePage(1);
      return result;
    } catch (err) {
      setError(err.message || 'No se pudo guardar el grupo.');
    } finally { setSaving(false); }
  }

  function beginEdit(group) {
    setEditingGroupId(group.id);
    setGroupForm({ name: group.name, code: group.code, max_teams: group.max_teams });
    setError(''); setNotice('');
  }

  async function deleteGroup(group) {
    if (!window.confirm(`¿Eliminar el grupo «${group.name}» y sus asignaciones?`)) return;
    setSaving(true); setError(''); setNotice('');
    try {
      await apiRequest(`${basePath}/${group.id}`, { method: 'DELETE' });
      setNotice(`Se eliminó el grupo «${group.name}».`);
      if (editingGroupId === group.id) resetForm();
      await loadGroups();
    } catch (err) { setError(err.message || 'No se pudo eliminar el grupo.'); }
    finally { setSaving(false); }
  }

  async function assignTeam(group) {
    const registrationId = Number(selectionByGroup[group.id]);
    if (!registrationId) { setError('Selecciona una inscripción aprobada para agregarla al grupo.'); return; }
    setSaving(true); setError(''); setNotice('');
    try {
      await apiRequest(`${basePath}/${group.id}/registrations`, {
        method: 'POST', body: JSON.stringify({ registration_id: registrationId }),
      });
      setSelectionByGroup((current) => ({ ...current, [group.id]: '' }));
      setNotice('Equipo e integrantes agregados al grupo.');
      await loadGroups();
    } catch (err) { setError(err.message || 'No se pudo asignar el equipo.'); }
    finally { setSaving(false); }
  }

  async function moveTeam(group, team) {
    const targetGroupId = Number(moveTargets[team.registration_id]);
    if (!targetGroupId || targetGroupId === group.id) return;
    setSaving(true); setError(''); setNotice('');
    try {
      await apiRequest(`${basePath}/${targetGroupId}/registrations/${team.registration_id}`, { method: 'PUT' });
      setNotice(`Se movió ${team.team} a ${groups.find((item) => item.id === targetGroupId)?.name || 'otro grupo'}.`);
      await loadGroups();
    } catch (err) { setError(err.message || 'No se pudo mover el equipo.'); }
    finally { setSaving(false); }
  }

  async function removeTeam(group, team) {
    setSaving(true); setError(''); setNotice('');
    try {
      await apiRequest(`${basePath}/${group.id}/registrations/${team.registration_id}`, { method: 'DELETE' });
      setNotice(`Se quitó ${team.team} del grupo; la inscripción sigue intacta.`);
      await loadGroups();
    } catch (err) { setError(err.message || 'No se pudo quitar el equipo del grupo.'); }
    finally { setSaving(false); }
  }

  if (!isOpen) return null;

  const content = <section className={`group-management-modal${embedded ? ' embedded' : ''}`} role={embedded ? undefined : 'dialog'} aria-modal={embedded ? undefined : 'true'} aria-labelledby="group-management-title">
      <header className="group-management-header">
        <div><span>ORGANIZACIÓN DE COMPETENCIA</span><h2 id="group-management-title">Grupos del torneo</h2>
          <p>{event?.name || 'Evento'} · crea grupos por categoría y asigna inscripciones aprobadas.</p></div>
        <button type="button" onClick={onClose} aria-label="Cerrar">×</button>
      </header>

      {error && <div className="group-management-alert" role="alert">{error}</div>}
      {notice && <div className="group-management-notice" role="status">{notice}</div>}
      {locked && <div className="group-management-locked" role="status">{lockReason || 'El torneo ya inició; la gestión está bloqueada.'}</div>}

      <div className="group-management-toolbar">
        {!embedded && <label htmlFor="group-category-select">Categoría
          <select id="group-category-select" value={categoryId} onChange={(e) => { setCategoryId(e.target.value); setEligiblePage(1); resetForm(); setNotice(''); setError(''); }}>
            {!categories.length && <option value="">No hay categorías activas</option>}
            {categories.map((item) => <option key={item.category_id} value={item.category_id}>{item.category_name}</option>)}
          </select>
        </label>}
        <span>{groups.length} grupos configurados · {eligibleInfo.total} inscripciones aprobadas sin asignar</span>
      </div>

      {!loading && !categories.length && <div className="group-management-empty">Este evento todavía no tiene categorías activas. Configura una categoría antes de crear grupos.</div>}
      {loading ? <div className="group-management-empty">Cargando grupos e inscripciones…</div> : <>
        <form className="group-management-form" onSubmit={saveGroup}>
          <h3>{editingGroupId ? 'Editar grupo' : 'Crear grupo'}</h3>
          <label>Nombre<input required maxLength={100} value={groupForm.name} onChange={(e) => setGroupForm((current) => ({ ...current, name: e.target.value }))} placeholder="Ej.: Grupo Norte" /></label>
          <label>Código<input required maxLength={20} pattern="[A-Za-z0-9_\\-]+" value={groupForm.code} onChange={(e) => setGroupForm((current) => ({ ...current, code: e.target.value.toUpperCase() }))} placeholder="Ej.: NORTE" /></label>
          <label>Máximo de equipos<input required type="number" min="1" max="64" step="1" value={groupForm.max_teams} onChange={(e) => setGroupForm((current) => ({ ...current, max_teams: e.target.value }))} /></label>
          <div className="group-management-form-actions"><button className="group-management-primary" type="submit" disabled={saving || locked || !categoryId}>{saving ? 'Guardando…' : editingGroupId ? 'Guardar cambios' : 'Crear grupo'}</button>
            {editingGroupId && <button type="button" onClick={resetForm}>Cancelar edición</button>}</div>
        </form>

        {!groups.length && <div className="group-management-empty">Aún no hay grupos para esta categoría. Créelos con el formulario para comenzar.</div>}
        <div className="group-management-grid">
          {groups.map((group) => <article className="group-management-card" key={group.id}>
            <header><div><span>CÓDIGO {group.code}</span><h3>{group.name}</h3></div><strong>{group.assigned_count}/{group.max_teams} equipos</strong></header>
            <div className="group-management-card-actions"><button type="button" disabled={saving || locked} onClick={() => beginEdit(group)}>Editar</button><button type="button" className="danger" disabled={saving || locked} onClick={() => deleteGroup(group)}>Eliminar grupo</button></div>
            {!locked && <div className="group-management-assign"><label htmlFor={`assign-${group.id}`}>Inscripción aprobada
              <select id={`assign-${group.id}`} value={selectionByGroup[group.id] || ''} disabled={saving || group.assigned_count >= group.max_teams || !eligible.length} onChange={(e) => setSelectionByGroup((current) => ({ ...current, [group.id]: e.target.value }))}>
                <option value="">Selecciona un equipo…</option>
                {eligible.map((item) => <option key={item.registration_id} value={item.registration_id}>{item.team} · {item.robot} · {item.people_count} integrantes</option>)}
              </select></label><button type="button" className="group-management-primary" disabled={saving || group.assigned_count >= group.max_teams || !selectionByGroup[group.id]} onClick={() => assignTeam(group)}>Agregar al grupo</button>
            </div>}
            {!locked && eligibleInfo.total_pages > 1 && <div className="group-management-pagination"><button type="button" disabled={eligiblePage <= 1 || saving} onClick={() => setEligiblePage((page) => page - 1)}>Inscripciones anteriores</button><span>Página {eligiblePage} de {eligibleInfo.total_pages}</span><button type="button" disabled={eligiblePage >= eligibleInfo.total_pages || saving} onClick={() => setEligiblePage((page) => page + 1)}>Siguientes</button></div>}
            {!group.teams.length ? <p className="group-management-empty compact">Todavía no hay equipos asignados.</p> : <div className="group-management-teams">
              {group.teams.map((team) => <section className="group-management-team" key={team.registration_id}>
                <div className="group-management-team-heading"><div><strong>{team.team} · {team.robot}</strong></div><small>{team.registration_status === 'APPROVED' ? 'Aprobado' : team.registration_status}</small></div>
                {!locked && <div className="group-management-team-actions"><label>Mover a<select value={moveTargets[team.registration_id] || ''} onChange={(e) => setMoveTargets((current) => ({ ...current, [team.registration_id]: e.target.value }))}><option value="">Seleccionar grupo</option>{groups.filter((other) => other.id !== group.id && other.assigned_count < other.max_teams).map((other) => <option key={other.id} value={other.id}>{other.name} · {other.assigned_count}/{other.max_teams}</option>)}</select></label><button type="button" disabled={saving || !moveTargets[team.registration_id]} onClick={() => moveTeam(group, team)}>Mover</button><button type="button" className="danger" disabled={saving} onClick={() => removeTeam(group, team)}>Quitar</button></div>}
              </section>)}
            </div>}
          </article>)}
        </div>
      </>}
      {!embedded && <footer className="group-management-footer"><span>Evento seleccionado: {event?.name}. Las inscripciones se conservan intactas.</span><button type="button" onClick={onClose}>Cerrar</button></footer>}
    </section>;

  return embedded ? content : <div className="group-management-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>{content}</div>;
}
