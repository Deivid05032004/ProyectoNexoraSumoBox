import { useCallback, useEffect, useMemo, useState } from 'react';
import { adminWebSocketUrl, apiRequest } from '../services/adminApi';
import { obtenerTodasLasInscripciones } from '../services/adminInscripcionesApi';
import GroupManagement from './GroupManagement';
import TournamentPhaseTransition from '../../ModuloResultados/TournamentPhaseTransition';
import './TournamentManager.css';

const PHASES = { NOT_CONFIGURED: 'Sin configurar', GROUP: 'Fase de grupos', ROUND_OF_64: 'Ronda de 64', ROUND_OF_32: 'Ronda de 32', ROUND_OF_16: 'Octavos de final', QUARTERFINAL: 'Cuartos de final', SEMIFINAL: 'Semifinales', THIRD_PLACE: 'Tercer puesto', FINAL: 'Gran final', FINISHED: 'Torneo finalizado' };
const BRACKET_NEXT = { ROUND_OF_64: 'ROUND_OF_32', ROUND_OF_32: 'ROUND_OF_16', ROUND_OF_16: 'QUARTERFINAL', QUARTERFINAL: 'SEMIFINAL', SEMIFINAL: 'THIRD_PLACE', THIRD_PLACE: 'FINAL' };

function initialKnockoutPhase(qualifierCount) {
  if (qualifierCount <= 2) return 'FINAL';
  const size = 2 ** Math.ceil(Math.log2(qualifierCount));
  return ({ 4: 'SEMIFINAL', 8: 'QUARTERFINAL', 16: 'ROUND_OF_16',
    32: 'ROUND_OF_32', 64: 'ROUND_OF_64' })[size] || null;
}

function tournamentPhaseSteps(groupCount) {
  const steps = ['GROUP'];
  let phase = initialKnockoutPhase(groupCount * 2);
  while (phase && steps.length < 8) {
    steps.push(phase);
    if (phase === 'FINAL') break;
    phase = phase === 'SEMIFINAL' ? 'THIRD_PLACE'
      : phase === 'THIRD_PLACE' ? 'FINAL' : BRACKET_NEXT[phase];
  }
  return steps;
}

function phaseExplanation(phase, groupCount) {
  if (phase === 'GROUP') {
    const next = initialKnockoutPhase(groupCount * 2);
    return `Clasifican los 2 mejores de cada grupo. Con ${groupCount} grupos (${groupCount * 2} clasificados), la siguiente fase será ${PHASES[next] || 'la llave eliminatoria'}. Al terminar todos los encuentros, revisa la clasificación y confirma el avance.`;
  }
  if (phase === 'QUARTERFINAL') return 'Los ganadores de cuartos avanzan a semifinales.';
  if (phase === 'SEMIFINAL') return 'Los ganadores disputarán la final; los otros dos jugarán por el tercer puesto.';
  if (phase === 'THIRD_PLACE') return 'Este combate define el tercer puesto. Al terminar, se habilita la final entre los ganadores de semifinales.';
  if (phase === 'FINAL') return 'Al terminar la final, revisa el resultado y confirma el cierre para anunciar oficialmente al campeón.';
  if (phase === 'FINISHED') return 'La llave terminó y el campeón quedó definido.';
  return `Los ganadores avanzan a ${PHASES[BRACKET_NEXT[phase]] || 'la siguiente ronda'}.`;
}

function approvedTeams(rows, eventId, categoryId) {
  const approved = rows.filter((row) => row.estado === 'APPROVED' && Number(row.raw?.event_id) === Number(eventId)
    && Number(row.raw?.category_id) === Number(categoryId) && row.raw?.team_id && row.raw?.robot_id);
  return [...new Map(approved.map((row) => [String(row.raw.team_id), {
    team_id: Number(row.raw.team_id), robot_id: Number(row.raw.robot_id), team: row.equipo,
    robot: row.robot, institution: row.institucion,
  }])).values()];
}

export default function TournamentManager({ isOpen, event, onClose }) {
  const [registrations, setRegistrations] = useState([]);
  const [eventCategories, setEventCategories] = useState([]);
  const [categoryId, setCategoryId] = useState('');
  const [selectedGroupCode, setSelectedGroupCode] = useState('');
  const [tournament, setTournament] = useState(null);
  const [configuredGroups, setConfiguredGroups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const categories = useMemo(() => eventCategories.filter((category) => category.is_active !== false), [eventCategories]);
  const teams = useMemo(() => approvedTeams(registrations, event?.id, categoryId), [registrations, event?.id, categoryId]);
  const configured = Boolean(tournament && tournament.phase !== 'NOT_CONFIGURED');
  const groupReadiness = useMemo(() => {
    if (configuredGroups.length < 2) return ['Crea al menos dos grupos para esta categoría.'];
    return configuredGroups.flatMap((group) => {
      if (group.assigned_count < 2) return [`${group.name}: asigna al menos 2 equipos aprobados.`];
      if (group.assigned_count > group.max_teams) return [`${group.name}: supera su capacidad.`];
      return [];
    });
  }, [configuredGroups]);
  const onGroupStateChange = useCallback(({ groups }) => setConfiguredGroups(groups || []), []);

  const loadTournament = useCallback(async (selectedCategory) => {
    if (!event?.id || !selectedCategory) { setTournament(null); return; }
    try {
      const result = await apiRequest(`/api/v1/events/${event.id}/tournament?category_id=${selectedCategory}`);
      setTournament(result);
    } catch (err) { setError(err.message || 'No se pudo cargar el torneo.'); }
  }, [event?.id]);

  useEffect(() => {
    if (!isOpen || !event?.id) return undefined;
    let alive = true;
    setLoading(true); setError('');
    Promise.all([
      obtenerTodasLasInscripciones({ eventId: event.id }),
      apiRequest(`/api/v1/events/${event.id}/categories?page=1&limit=100`),
    ]).then(([rows, categoryRows]) => {
      if (!alive) return;
      setRegistrations(rows);
      const availableCategories = (Array.isArray(categoryRows) ? categoryRows : [])
        .filter((category) => category.is_active !== false);
      setEventCategories(availableCategories);
      if (availableCategories.length) {
        const categoryIds = availableCategories.map((category) => Number(category.category_id ?? category.id));
        const current = categoryIds.includes(Number(categoryId)) ? Number(categoryId) : categoryIds[0];
        setCategoryId(String(current));
        void loadTournament(current);
      } else {
        setCategoryId('');
        setTournament(null);
      }
    }).catch((err) => { if (alive) setError(err.message || 'No se pudieron cargar los equipos aprobados.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [isOpen, event?.id, loadTournament]);

  useEffect(() => {
    if (!isOpen || !event?.id || !categoryId || typeof WebSocket === 'undefined') return undefined;
    let stopped = false;
    let socket;
    let retryTimer;
    let retryDelay = 1000;
    const url = adminWebSocketUrl(
      `/api/v1/events/${event.id}/live?category_id=${encodeURIComponent(categoryId)}`,
    );
    const connect = () => {
      if (stopped) return;
      try {
        socket = new WebSocket(url);
      } catch {
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
        return;
      }
      socket.onopen = () => { retryDelay = 1000; };
      socket.onmessage = ({ data }) => {
        try {
          const snapshot = JSON.parse(data);
          if (Number(snapshot.event_id) === Number(event.id)
              && Number(snapshot.tournament?.category_id) === Number(categoryId)) {
            setTournament(snapshot.tournament);
          }
        } catch { /* La siguiente instantánea vuelve a sincronizar el panel. */ }
      };
      socket.onclose = () => {
        if (stopped) return;
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [isOpen, event?.id, categoryId]);

  async function selectCategory(value) {
    setCategoryId(value); setError(''); setNotice('');
    setSelectedGroupCode('');
    const selected = Number(value);
    await loadTournament(selected);
  }

  async function createTournament() {
    if (!categoryId || saving) return;
    setSaving(true); setError(''); setNotice('Validando grupos y generando encuentros…');
    try {
      const result = await apiRequest(`/api/v1/events/${event.id}/tournament/from-groups`, { method: 'POST', body: JSON.stringify({
        category_id: Number(categoryId),
      }) });
      setTournament(result); setNotice('Calendario creado desde las asignaciones guardadas.');
    } catch (err) { setError(err.message || 'No se pudo generar el torneo.'); setNotice(''); }
    finally { setSaving(false); }
  }

  async function mutate(path, body) {
    if (saving) return;
    setSaving(true); setError('');
    try {
      await apiRequest(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
      // The command endpoints keep returning the public combat payload for
      // existing clients; refresh this administrator's full tournament view.
      const next = await apiRequest(`/api/v1/events/${event.id}/tournament?category_id=${categoryId}`);
      setTournament(next);
      setNotice('Actualización guardada y publicada en la pantalla en vivo.');
    } catch (err) { setError(err.message || 'No se pudo actualizar el marcador.'); }
    finally { setSaving(false); }
  }

  if (!isOpen) return null;
  const activeMatches = (tournament?.boards || []).filter((board) => board.match?.status === 'LIVE').length;
  const scheduledMatches = (tournament?.matches || []).filter((match) => match.stage_code === tournament?.phase && match.status === 'SCHEDULED').length;
  const phaseComplete = tournament?.phase === 'FINISHED';
  const groupCodes = Object.keys(tournament?.groups || {});
  const phaseSteps = tournamentPhaseSteps(groupCodes.length);
  const currentPhaseIndex = tournament?.phase === 'FINISHED' ? phaseSteps.length - 1
    : phaseSteps.indexOf(tournament?.phase);
  const phaseProgress = tournament?.phase_progress;
  const activeGroupCode = groupCodes.includes(selectedGroupCode) ? selectedGroupCode : (groupCodes[0] || '');
  const groupMatches = (tournament?.matches || []).filter((match) => match.stage_code === 'GROUP');
  const teamsInLiveMatches = new Set((tournament?.boards || []).filter((board) => board.match?.status === 'LIVE')
    .flatMap((board) => [board.match.team_id_a, board.match.team_id_b]));
  const eligibleGroupMatches = groupMatches.filter((match) => match.status === 'SCHEDULED'
    && !groupMatches.some((prior) => prior.group_code === match.group_code
      && Number(prior.schedule_round) < Number(match.schedule_round) && prior.status !== 'FINISHED')
    && !teamsInLiveMatches.has(match.team_id_a) && !teamsInLiveMatches.has(match.team_id_b));

  return <div className="tournament-modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="tournament-modal" role="dialog" aria-modal="true" aria-labelledby="tournament-title">
      <header className="tournament-header"><div><span>GESTIÓN DE FASES Y PUNTUACIÓN</span><h2 id="tournament-title">Torneo y marcador simultáneo</h2>
        <p>{event?.name || 'Evento'} · equipos aprobados · formato según categoría</p></div><button className="tournament-close" type="button" onClick={onClose} aria-label="Cerrar">×</button></header>
      {error && <div className="tournament-alert" role="alert">{error}</div>}{notice && <div className="tournament-notice" role="status">{notice}</div>}
      {loading ? <div className="tournament-loading">Cargando inscripciones aprobadas…</div> : <>
        <TournamentPhaseTransition tournament={tournament} audience="admin" />
        <div className="tournament-toolbar"><label>Categoría<select value={categoryId} onChange={(e) => selectCategory(e.target.value)} disabled={!categories.length}>
          {!categories.length && <option value="">Este evento no tiene categorías activas</option>}
          {categories.map((item) => <option key={item.category_id ?? item.id} value={item.category_id ?? item.id}>{item.category_name ?? item.name}</option>)}
        </select></label><div className="tournament-phase-chip">FASE ACTUAL <strong>{PHASES[tournament?.phase || 'NOT_CONFIGURED']}</strong></div></div>
        {!configured ? <>
          <div className="tournament-setup-note">Para este evento y categoría, crea los grupos y define la capacidad de cada uno. Asigna solo equipos aprobados; el sistema programa todos contra todos sin repetir cruces. Clasifican los dos mejores de cada grupo y, si la llave no es potencia de dos, los mejores sembrados reciben pase automático. Con cuatro grupos se conserva la llave oficial del jueves.</div>
          <GroupManagement isOpen embedded event={event} selectedCategoryId={categoryId} onStateChange={onGroupStateChange} />
          {groupReadiness.length > 0 && <div className="tournament-setup-note tournament-readiness" role="status"><strong>Completa la configuración de grupos:</strong> {groupReadiness.join(' ')}</div>}
          <footer className="tournament-footer"><span>{teams.length} equipos aprobados · {configuredGroups.length} grupos configurados</span><button type="button" className="tournament-primary" onClick={createTournament} disabled={saving || groupReadiness.length > 0}>{saving ? 'Generando…' : 'Crear calendario e iniciar gestión de encuentros'}</button></footer>
        </> : <>
          {tournament.phase === 'GROUP' && <div className="tournament-summary">Cada grupo conserva su dohyo durante toda la fase. La tabla clasifica por combates ganados, diferencia de Yukos y duelo directo; los empates que el reglamento no resuelve se muestran como empate.</div>}
          <section className="tournament-phase-flow" aria-label="Avance de fases del torneo">
            <ol>{phaseSteps.map((step, index) => <li key={step}
              className={phaseComplete || index < currentPhaseIndex ? 'complete' : index === currentPhaseIndex ? 'current' : ''}>
              <span>{phaseComplete || index < currentPhaseIndex ? '✓' : index + 1}</span><b>{PHASES[step]}</b>
            </li>)}</ol>
            <p>{phaseExplanation(tournament.phase, groupCodes.length)}</p>
            {phaseProgress?.total > 0 && <div className="tournament-progress-wrap">
              <div className="tournament-progress-label"><b>{PHASES[phaseProgress.stage] || 'Fase actual'}</b>
                <span>{phaseProgress.finished} de {phaseProgress.total} encuentros finalizados · {phaseProgress.live} en vivo · {phaseProgress.scheduled} programados</span></div>
              <div className="tournament-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax={phaseProgress.total} aria-valuenow={phaseProgress.finished}>
                <span style={{ width: `${Math.round((phaseProgress.finished / phaseProgress.total) * 100)}%` }} />
              </div>
              {!phaseProgress.complete && <small>La fase seguirá activa hasta que se completen todos sus encuentros.</small>}
              {phaseProgress.complete && tournament.can_advance && <div className="tournament-phase-ready" role="status">
                <div><b>Fase completada</b><span>Los resultados están guardados. Revisa la clasificación y confirma {tournament.next_phase === 'FINISHED' ? 'el cierre oficial del torneo' : `el avance a ${PHASES[tournament.next_phase] || tournament.next_phase}`}.</span></div>
                <button type="button" className="tournament-advance-phase" disabled={saving}
                  onClick={() => mutate(`/api/v1/events/${event.id}/tournament/advance-phase?category_id=${categoryId}`)}>
                  {saving ? 'Preparando fase…' : tournament.next_phase === 'FINISHED'
                    ? 'Confirmar campeón y finalizar torneo →'
                    : `Avanzar a ${PHASES[tournament.next_phase] || tournament.next_phase} →`}
                </button>
              </div>}
            </div>}
            {new Set(groupCodes).size === 4 && ['A', 'B', 'C', 'D'].every((code) => groupCodes.includes(code))
              && <small className="tournament-official-bracket">Cuartos: 1.º A vs. 2.º B · 1.º C vs. 2.º D · 1.º B vs. 2.º A · 1.º D vs. 2.º C. En semifinales se cruzan los ganadores QF1–QF2 y QF3–QF4.</small>}
          </section>
          {tournament.unresolved_qualifying_ties?.length > 0 && <div className="tournament-unresolved-tie" role="status">
            No se puede avanzar a eliminatorias todavía. El desempate de {tournament.unresolved_qualifying_ties
              .map((code) => tournament.group_names?.[code] || `Grupo ${code}`).join(', ')} no queda resuelto por los criterios actuales; se necesita una decisión reglamentaria.
          </div>}
          {tournament.phase === 'GROUP' && <>
            <nav className="tournament-group-tabs" aria-label="Vistas de grupos">
              {groupCodes.map((code) => <button type="button" key={code}
                className={activeGroupCode === code ? 'active' : ''}
                aria-pressed={activeGroupCode === code}
                onClick={() => setSelectedGroupCode(code)}>
                {tournament.group_names?.[code] || `Grupo ${code}`}
              </button>)}
            </nav>
            {activeGroupCode && (() => {
              const rows = tournament.groups?.[activeGroupCode] || [];
              const groupMatchesForView = groupMatches.filter((match) => match.group_code === activeGroupCode);
              const nextMatch = eligibleGroupMatches.find((match) => match.group_code === activeGroupCode) || null;
              const groupDohyoNumber = nextMatch?.dohyo_number || groupMatchesForView[0]?.dohyo_number || 1;
              const groupBoard = (tournament.boards || []).find((board) => board.dohyo_number === groupDohyoNumber);
              const shownMatch = (groupBoard?.match?.group_code === activeGroupCode ? groupBoard.match : null)
                || groupMatchesForView.find((match) => match.status === 'LIVE')
                || [...groupMatchesForView].reverse()
                .find((match) => match.status === 'FINISHED') || null;
              const dohyoBusyForAnotherGroup = groupBoard?.match?.status === 'LIVE'
                && groupBoard.match.group_code !== activeGroupCode;
              return <section className="tournament-group-view" aria-label={`Vista exclusiva de ${tournament.group_names?.[activeGroupCode] || `Grupo ${activeGroupCode}`}`}>
                <header><div><span>VISTA EXCLUSIVA DEL GRUPO</span><h3>{tournament.group_names?.[activeGroupCode] || `Grupo ${activeGroupCode}`}</h3></div>
                  <b>{rows.length} equipos · Dohyo {groupDohyoNumber}</b></header>
                <ol className="tournament-group-standings">{rows.map((team) => <li key={team.team_id} className={team.rank <= 2 ? 'provisional-qualifier' : ''}>
                  <span><b>{team.rank}.</b> {team.team} · {team.robot}</span>
                  <strong>{team.wins} combates · {team.yukos_for}–{team.yukos_against} Yukos · Δ {team.difference}</strong>
                  {team.rank <= 2 && tournament.phase === 'GROUP' && <small className="tournament-qualifier-badge">{phaseProgress?.complete && !tournament.unresolved_qualifying_ties?.length ? 'Clasificación oficial' : 'En zona de clasificación'}</small>}
                  {team.tie_status === 'UNRESOLVED' && <small className="tournament-tie-badge">Empate sin resolver por reglamento</small>}
                  {team.tie_breaker === 'HEAD_TO_HEAD' && <small className="tournament-tie-badge">Ordenado por duelo directo</small>}
                </li>)}</ol>
                {shownMatch ? <article className="tournament-board tournament-group-match">
                  <div className="tournament-board-title"><b>{groupBoard ? `Dohyo ${groupBoard.dohyo_number} · ` : ''}Encuentro del grupo</b>
                    <span>{shownMatch.status === 'LIVE' ? 'EN VIVO' : shownMatch.status === 'FINISHED' ? 'FINALIZADO' : 'PROGRAMADO'}</span></div>
                  <div className="tournament-contest"><span><strong>{shownMatch.robot_a}</strong><small>{shownMatch.team_a} · rojo</small></span><b>{shownMatch.score_a}</b></div>
                  <div className="tournament-contest"><span><strong>{shownMatch.robot_b}</strong><small>{shownMatch.team_b} · azul</small></span><b>{shownMatch.score_b}</b></div>
                  {shownMatch.status === 'LIVE' && <div className="tournament-score-actions">
                    <button type="button" disabled={saving || shownMatch.score_a <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${shownMatch.match_id}/yukos?category_id=${categoryId}`, { team_id: shownMatch.team_id_a, points_delta: -1 })}>− rojo</button>
                    <button type="button" disabled={saving || shownMatch.score_a >= shownMatch.score_to_win} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${shownMatch.match_id}/yukos?category_id=${categoryId}`, { team_id: shownMatch.team_id_a, points_delta: 1 })}>+1 rojo</button>
                    <button type="button" disabled={saving || shownMatch.score_b >= shownMatch.score_to_win} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${shownMatch.match_id}/yukos?category_id=${categoryId}`, { team_id: shownMatch.team_id_b, points_delta: 1 })}>+1 azul</button>
                    <button type="button" disabled={saving || shownMatch.score_b <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${shownMatch.match_id}/yukos?category_id=${categoryId}`, { team_id: shownMatch.team_id_b, points_delta: -1 })}>− azul</button>
                  </div>}
                  {shownMatch.status === 'FINISHED' && <div className="tournament-finished">Ganador: {shownMatch.winner_team_id === shownMatch.team_id_a ? shownMatch.team_a : shownMatch.team_b}</div>}
                  <small className="tournament-score-rule">Primero a {shownMatch.score_to_win} Yukos</small>
                </article> : <div className="tournament-group-waiting">Este grupo aún no tiene un encuentro activo.</div>}
                {nextMatch && <div className="tournament-next-group-match">
                  <span>Siguiente encuentro: <b>{nextMatch.team_a}</b> vs. <b>{nextMatch.team_b}</b></span>
                  <button type="button" className="tournament-primary" disabled={saving || dohyoBusyForAnotherGroup}
                    onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${nextMatch.match_id}/start?category_id=${categoryId}&dohyo_number=${groupDohyoNumber}`)}>
                    {dohyoBusyForAnotherGroup ? `Dohyo ${groupDohyoNumber} ocupado` : `Iniciar en Dohyo ${groupDohyoNumber}`}
                  </button>
                </div>}
                {!nextMatch && groupMatchesForView.some((match) => match.status === 'SCHEDULED')
                  && <p className="tournament-group-waiting">La siguiente pelea de este grupo espera a que termine su combate anterior.</p>}
                {!nextMatch && groupMatchesForView.length > 0 && groupMatchesForView.every((match) => match.status === 'FINISHED')
                  && <p className="tournament-group-waiting">Todos los encuentros de este grupo terminaron.</p>}
              </section>;
            })()}
          </>}
          {tournament.phase !== 'GROUP' && <div className="tournament-board-grid">{(tournament.boards || []).filter((board) => board.match).map((board) => { const match = board.match;
            const groupLabel = match.group_code ? (match.group_name || tournament.group_names?.[match.group_code] || `Grupo ${match.group_code}`) : match.bracket_slot || match.stage_code;
            return <article className="tournament-board" key={board.dohyo_number}><div className="tournament-board-title"><b>Dohyo {board.dohyo_number} · {groupLabel}</b><span>{match.status === 'LIVE' ? 'EN VIVO' : match.status === 'FINISHED' ? 'FINALIZADO' : 'PROGRAMADO'}</span></div>
              <div className="tournament-contest"><span><strong>{match.robot_a}</strong><small>{match.team_a} · rojo</small></span><b>{match.score_a}</b></div>
              <div className="tournament-contest"><span><strong>{match.robot_b}</strong><small>{match.team_b} · azul</small></span><b>{match.score_b}</b></div>
              {match.status === 'FINISHED' ? <><div className="tournament-finished">Ganador: {match.winner_team_id === match.team_id_a ? match.team_a : match.team_b}
                {scheduledMatches > 0 && <button type="button" disabled={saving} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/dohyos/${board.dohyo_number}/advance?category_id=${categoryId}`)}>Siguiente combate</button>}</div>
                </>
                : match.status === 'LIVE' ? <div className="tournament-score-actions"><button type="button" disabled={saving || match.score_a <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_a, points_delta: -1 })}>− rojo</button><button type="button" disabled={saving || match.score_a >= match.score_to_win} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_a, points_delta: 1 })}>+1 rojo</button><button type="button" disabled={saving || match.score_b >= match.score_to_win} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_b, points_delta: 1 })}>+1 azul</button><button type="button" disabled={saving || match.score_b <= 0} onClick={() => mutate(`/api/v1/events/${event.id}/tournament/matches/${match.match_id}/yukos?category_id=${categoryId}`, { team_id: match.team_id_b, points_delta: -1 })}>− azul</button></div> : null}
              <small className="tournament-score-rule">Primero a {match.score_to_win} Yukos</small></article>;
          })}{activeMatches === 0 && scheduledMatches === 0 && !phaseComplete && <article className="tournament-board empty"><b>{PHASES[tournament.phase]}</b><span>Todos los encuentros de esta fase terminaron.</span></article>}</div>}
          {phaseComplete && (() => { const finalMatch = (tournament.matches || []).find((match) => match.stage_code === 'FINAL');
            const winner = finalMatch?.winner_team_id === finalMatch?.team_id_a ? finalMatch.team_a
              : finalMatch?.winner_team_id === finalMatch?.team_id_b ? finalMatch.team_b : '—';
            return <div className="tournament-champion">Torneo finalizado · campeón: {winner}</div>; })()}
          <div className="tournament-standings-grid"><article className="tournament-history"><h3>Encuentros de esta categoría</h3>{(tournament.matches || []).map((match) => <div key={match.match_id}><span>{PHASES[match.stage_code] || match.stage_code} · {match.group_name || match.group_code || match.bracket_slot}</span><b>{match.team_a} {match.score_a}–{match.score_b} {match.team_b}</b></div>)}</article></div>
        </>}
      </>}
      <footer className="tournament-modal-footer"><span>Los cambios se guardan en SQL y se emiten por el WebSocket del marcador.</span><button type="button" onClick={onClose}>Cerrar</button></footer>
    </section>
  </div>;
}
