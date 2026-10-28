import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiRequest } from '../services/adminApi';
import { obtenerTodasLasInscripciones } from '../services/adminInscripcionesApi';
import './TournamentManager.css';

const GROUPS = ['A', 'B', 'C', 'D'];
const PHASES = { NOT_CONFIGURED: 'Sin configurar', GROUP: 'Fase de grupos', QUARTERFINAL: 'Cuartos de final', SEMIFINAL: 'Semifinales', THIRD_PLACE: 'Tercer puesto', FINAL: 'Gran final', FINISHED: 'Torneo finalizado' };

function approvedTeams(rows, eventId, categoryId) {
  const approved = rows.filter((row) => row.estado === 'APPROVED' && Number(row.raw?.event_id) === Number(eventId)
    && Number(row.raw?.category_id) === Number(categoryId) && row.raw?.team_id && row.raw?.robot_id);
  return [...new Map(approved.map((row) => [String(row.raw.team_id), {
    team_id: Number(row.raw.team_id), robot_id: Number(row.raw.robot_id), team: row.equipo,
    robot: row.robot, institution: row.institucion,
  }])).values()];
}

function defaultAssignments(rows, eventId, categoryId) {
  return Object.fromEntries(approvedTeams(rows, eventId, categoryId).map((team, index) => {
    const group = index < 5 ? 'A' : index < 10 ? 'B' : index < 15 ? 'C' : 'D';
    return [`${team.team_id}:${team.robot_id}`, group];
  }));
}

export default function TournamentManager({ isOpen, event, onClose }) {
  const [registrations, setRegistrations] = useState([]);
  const [categoryId, setCategoryId] = useState('');
  const [assignments, setAssignments] = useState({});
  const [tournament, setTournament] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const categories = useMemo(() => [...new Map(registrations.filter((row) => row.estado === 'APPROVED'
    && Number(row.raw?.event_id) === Number(event?.id) && row.raw?.category_id)
    .map((row) => [Number(row.raw.category_id), { id: Number(row.raw.category_id), name: row.categoria }])).values()], [registrations, event?.id]);
  const teams = useMemo(() => approvedTeams(registrations, event?.id, categoryId), [registrations, event?.id, categoryId]);
  const configured = Boolean(tournament && tournament.phase !== 'NOT_CONFIGURED');

  const loadTournament = useCallback(async (selectedCategory) => {
    if (!event?.id || !selectedCategory) { setTournament(null); return; }
    try {
      const result = await apiRequest(`/api/v1/events/${event.id}/tournament?category_id=${selectedCategory}`);
      setTournament(result);
      if (result.phase !== 'NOT_CONFIGURED') {
        setAssignments(Object.fromEntries(Object.entries(result.groups || {}).flatMap(([group, rows]) =>
          rows.map((team) => [`${team.team_id}:${team.robot_id}`, group]))));
      }
    } catch (err) { setError(err.message || 'No se pudo cargar el torneo.'); }
  }, [event?.id]);

  useEffect(() => {
    if (!isOpen || !event?.id) return undefined;
    let alive = true;
    setLoading(true); setError('');
    obtenerTodasLasInscripciones({ eventId: event.id }).then((rows) => {
      if (!alive) return;
      setRegistrations(rows);
      const approvedCategories = [...new Map(rows.filter((row) => row.estado === 'APPROVED' && Number(row.raw?.event_id) === Number(event.id))
        .map((row) => [Number(row.raw.category_id), Number(row.raw.category_id)])).values()];
      if (approvedCategories.length) {
        const current = approvedCategories.includes(Number(categoryId)) ? Number(categoryId) : approvedCategories[0];
        setCategoryId(String(current));
        setAssignments(defaultAssignments(rows, event.id, current));
        void loadTournament(current);
      }
    }).catch((err) => { if (alive) setError(err.message || 'No se pudieron cargar los equipos aprobados.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [isOpen, event?.id, loadTournament]);

  async function selectCategory(value) {
    setCategoryId(value); setError(''); setNotice('');
    const selected = Number(value);
    setAssignments(defaultAssignments(registrations, event?.id, selected));
    await loadTournament(selected);
  }

  async function createTournament() {
    if (!categoryId || saving || !teams.length) return;
    const grouped = Object.fromEntries(GROUPS.map((group) => [group, teams.filter((team) => assignments[`${team.team_id}:${team.robot_id}`] === group)]));
    if (teams.length !== 21) { setError(`El torneo del jueves requiere 21 robots aprobados; hay ${teams.length} en esta categoría.`); return; }
    const expected = { A: 5, B: 5, C: 5, D: 6 };
    const wrongSize = GROUPS.filter((group) => grouped[group].length !== expected[group]);
    if (wrongSize.length) { setError('La distribución debe ser: A=5, B=5, C=5 y D=6 equipos.'); return; }
    const empty = GROUPS.filter((group) => !grouped[group].length);
    if (empty.length) { setError(`Asigna al menos un equipo a cada grupo: ${empty.join(', ')}.`); return; }
    setSaving(true); setError(''); setNotice('Generando todos contra todos…');
    try {
      const result = await apiRequest(`/api/v1/events/${event.id}/tournament`, { method: 'POST', body: JSON.stringify({
        category_id: Number(categoryId), teams: teams.map((team) => ({ ...team, group_code: assignments[`${team.team_id}:${team.robot_id}`] })),
      }) });
      setTournament(result); setNotice('Grupos y encuentros únicos guardados en la base de datos.');
    } catch (err) { setError(err.message || 'No se pudo generar el torneo.'); setNotice(''); }
    finally { setSaving(false); }
  }

  async function mutate(path, body) {
    if (saving) return;
    setSaving(true); setError('');
    try {
      const result = await apiRequest(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
      const next = result.tournament || result;
      setTournament(next);
      setNotice('Actualización guardada y publicada en la pantalla en vivo.');
    } catch (err) { setError(err.message || 'No se pudo actualizar el marcador.'); }
    finally { setSaving(false); }
  }

  if (!isOpen) return null;
  const activeMatches = (tournament?.boards || []).filter((board) => board.match).length;
  const phaseComplete = tournament?.phase === 'FINISHED';

  return <div className="tournament-modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="tournament-modal" role="dialog" aria-modal="true" aria-labelledby="tournament-title">
      <header className="tournament-header"><div><span>GESTIÓN DE FASES Y PUNTUACIÓN</span><h2 id="tournament-title">Torneo y marcador simultáneo</h2>
        <p>{event?.name || 'Evento'} · equipos aprobados · cuatro dohyos</p></div><button className="tournament-close" type="button" onClick={onClose} aria-label="Cerrar">×</button></header>
      {error && <div className="tournament-alert" role="alert">{error}</div>}{notice && <div className="tournament-notice" role="status">{notice}</div>}
      {loading ? <div className="tournament-loading">Cargando inscripciones aprobadas…</div> : <>
        <div className="tournament-toolbar"><label>Categoría<select value={categoryId} onChange={(e) => selectCategory(e.target.value)}>
          {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label><div className="tournament-phase-chip">FASE ACTUAL <strong>{PHASES[tournament?.phase || 'NOT_CONFIGURED']}</strong></div></div>
        {!configured ? <>
          <div className="tournament-setup-note">Asigna cada robot aprobado a un grupo. El sistema crea el todos contra todos, sin repetir enfrentamientos, y registra los puntos en la base de datos.</div>
          <div className="tournament-team-list">{teams.map((team) => { const key = `${team.team_id}:${team.robot_id}`; return <div className="tournament-team-row" key={key}>
            <div><strong>{team.team}</strong><span>{team.robot} · {team.institution}</span></div><select aria-label={`Grupo para ${team.team}`} value={assignments[key] || ''}
              onChange={(e) => setAssignments((current) => ({ ...current, [key]: e.target.value }))}>
              <option value="">Elegir grupo</option>{GROUPS.map((group) => <option key={group} value={group}>Grupo {group}</option>)}
            </select></div>; })}{!teams.length && <p>No hay inscripciones aprobadas en esta categoría.</p>}</div>
          <footer className="tournament-footer"><span>{teams.length} robots aprobados · grupos A, B, C y D</span><button type="button" className="tournament-primary" onClick={createTournament} disabled={saving || !teams.length}>{saving ? 'Guardando…' : 'Guardar grupos y crear encuentros'}</button></footer>
        </> : <>
          {tournament.phase === 'GROUP' && <div className="tournament-summary">Un combate activo por grupo · primero en ganar 2 Yukos · orden de grupo por victorias, diferencia y duelo directo.</div>}
          {tournament.phase === 'GROUP' && <div className="tournament-standings-grid">{GROUPS.map((group) => <article key={group}><h3>Grupo {group}</h3><ol>{(tournament.groups?.[group] || []).map((team) => <li key={team.team_id}><span>{team.team} · {team.robot}</span><b>{team.wins} G · {team.yukos_for}–{team.yukos_against} ({team.difference > 0 ? '+' : ''}{team.difference})</b></li>)}</ol></article>)}</div>}
          <div className="tournament-board-grid">{(tournament.boards || []).map((board) => { const match = board.match; if (!match) return <article className="tournament-board empty" key={board.dohyo_number}><b>Dohyo {board.dohyo_number}</b><span>Sin encuentro activo</span></article>;
            const groupLabel = match.group_code ? `Grupo ${match.group_code}` : match.bracket_slot || match.stage_code;
            return <article className="tournament-board" key={board.dohyo_number}><div className="tournament-board-title"><b>Dohyo {board.dohyo_number} · {groupLabel}</b><span>{match.status === 'LIVE' ? 'EN VIVO' : match.status === 'FINISHED' ? 'FINALIZADO' : 'PROGRAMADO'}</span></div>
              <div className="tournament-contest"><span><strong>{match.robot_a}</strong><small>{match.team_a} · rojo</small></span><b>{match.score_a}</b></div>
              <div className="tournament-contest"><span><strong>{match.robot_b}</strong><small>{match.team_b} · azul</small></span><b>{match.score_b}</b></div>
              {match.status === 'FINISHED' ? <><div className="tournament-finished">Ganador: {match.winner_team_id === match.team_id_a ? match.team_a : match.team_b}
                {match.stage_code === 'GROUP' && <button type="button" disabled={saving} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/dohyos/${board.dohyo_number}/advance?category_id=${categoryId}`)}>Siguiente combate</button>}</div>
                {match.stage_code === 'GROUP' && <div className="tournament-score-actions"><button type="button" disabled={saving || match.score_a <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_a, points_delta: -1 })}>Corregir − rojo</button><button type="button" disabled={saving || match.score_b <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_b, points_delta: -1 })}>Corregir − azul</button></div>}</>
                : match.status === 'LIVE' ? <div className="tournament-score-actions"><button type="button" disabled={saving || match.score_a <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_a, points_delta: -1 })}>− rojo</button><button type="button" disabled={saving || match.score_a >= match.score_to_win} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_a, points_delta: 1 })}>+1 rojo</button><button type="button" disabled={saving || match.score_b >= match.score_to_win} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_b, points_delta: 1 })}>+1 azul</button><button type="button" disabled={saving || match.score_b <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_b, points_delta: -1 })}>− azul</button></div> : null}
              <small className="tournament-score-rule">Primero a {match.score_to_win} Yukos</small></article>;
          })}</div>
          {activeMatches === 0 && !phaseComplete && <button type="button" className="tournament-primary" disabled={saving} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/start?category_id=${categoryId}`)}>Iniciar torneo</button>}
          {phaseComplete && (() => { const finalMatch = (tournament.matches || []).find((match) => match.stage_code === 'FINAL');
            const winner = finalMatch?.winner_team_id === finalMatch?.team_id_a ? finalMatch.team_a
              : finalMatch?.winner_team_id === finalMatch?.team_id_b ? finalMatch.team_b : '—';
            return <div className="tournament-champion">Torneo finalizado · campeón: {winner}</div>; })()}
          <div className="tournament-standings-grid"><article className="tournament-history"><h3>Encuentros de esta categoría</h3>{(tournament.matches || []).map((match) => <div key={match.match_id}><span>{PHASES[match.stage_code === 'GROUP' ? 'GROUP' : match.stage_code === 'QUARTERFINAL' ? 'QUARTERFINAL' : match.stage_code === 'SEMIFINAL' ? 'SEMIFINAL' : match.stage_code === 'THIRD_PLACE' ? 'THIRD_PLACE' : 'FINAL']} · {match.group_code || match.bracket_slot}</span><b>{match.team_a} {match.score_a}–{match.score_b} {match.team_b}</b></div>)}</article></div>
        </>}
      </>}
      <footer className="tournament-modal-footer"><span>Los cambios se guardan en SQL y se emiten por el WebSocket del marcador.</span><button type="button" onClick={onClose}>Cerrar</button></footer>
    </section>
  </div>;
}
