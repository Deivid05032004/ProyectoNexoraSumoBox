import { useEffect, useRef, useState } from 'react';
import TournamentPhaseTransition from './TournamentPhaseTransition';
import './TorneoEnVivo.css';

const PHASES = {
  GROUP: 'Fase de grupos', ROUND_OF_64: 'Ronda de 64', ROUND_OF_32: 'Ronda de 32',
  ROUND_OF_16: 'Octavos de final', QUARTERFINAL: 'Cuartos de final',
  SEMIFINAL: 'Semifinales', THIRD_PLACE: 'Combate por el tercer puesto',
  FINAL: 'Gran final', FINISHED: 'Torneo finalizado',
};
const PHASES_SMALL = { GROUP: 'GRUPO', QUARTERFINAL: 'CUARTOS', SEMIFINAL: 'SEMIFINAL',
  THIRD_PLACE: '3.º / 4.º LUGAR', FINAL: 'GRAN FINAL' };

function CombatCard({ board }) {
  const match = board.match;
  const matchId = match?.match_id;
  const matchStatus = match?.status;
  const prior = useRef(null);
  const [motion, setMotion] = useState('');

  useEffect(() => {
    const before = prior.current;
    let timer;
    if (before && matchId && before.match_id !== matchId) {
      setMotion('is-entering');
      timer = window.setTimeout(() => setMotion(''), 780);
    } else if (before && matchId && before.status !== 'FINISHED' && matchStatus === 'FINISHED') {
      setMotion('is-finishing');
      timer = window.setTimeout(() => setMotion(''), 1050);
    }
    prior.current = matchId ? { match_id: matchId, status: matchStatus } : null;
    return () => window.clearTimeout(timer);
  }, [matchId, matchStatus]);

  if (!match) return <article className="tournament-live-court is-empty">
    <header><span>DOHYO {board.dohyo_number}</span><b>En espera</b></header>
    <div>El administrador aún no ha seleccionado un encuentro.</div>
  </article>;
  const aWinner = match.winner_team_id === match.team_id_a;
  const bWinner = match.winner_team_id === match.team_id_b;
  const status = match.status === 'LIVE' ? 'EN VIVO' : match.status === 'FINISHED' ? 'FINALIZADO' : 'PROGRAMADO';
  return <article className={`tournament-live-court ${match.status === 'FINISHED' ? 'is-finished' : ''} ${motion}`}>
    <header><div><span>DOHYO {board.dohyo_number} · {PHASES_SMALL[match.stage_code] || match.stage_code}{match.group_code ? ` · GRUPO ${match.group_code}` : ''}</span>
      <h2>{match.bracket_slot || `Encuentro ${match.match_number}`}</h2></div>
      <b className={match.status === 'LIVE' ? 'live' : ''}>{status}</b></header>
    <div className={`tournament-live-side red ${aWinner ? 'winner' : ''}`}><div><small>ESQUINA ROJA</small><strong>{match.robot_a}</strong><span>{match.team_a}</span><em>{match.institution_a || 'Institución no registrada'}</em></div><b>{match.score_a}</b></div>
    <div className="tournament-live-vs">VS</div>
    <div className={`tournament-live-side blue ${bWinner ? 'winner' : ''}`}><div><small>ESQUINA AZUL</small><strong>{match.robot_b}</strong><span>{match.team_b}</span><em>{match.institution_b || 'Institución no registrada'}</em></div><b>{match.score_b}</b></div>
    <footer><span>{match.status === 'FINISHED' ? `🏆 Ganador: ${aWinner ? match.team_a : bWinner ? match.team_b : 'Pendiente de confirmar'}` : `Primero a ${match.score_to_win} Yukos`}</span>
      <span>{match.status === 'LIVE' ? 'Puntaje actualizado en vivo' : match.status === 'FINISHED' ? 'Resultado confirmado' : 'Programado'}</span></footer>
  </article>;
}

function PhaseResults({ tournament, phase }) {
  const progress = tournament.phase_progress;
  if (!progress?.complete || phase === 'FINISHED') return null;
  const matches = (tournament.matches || []).filter((match) => match.stage_code === phase);
  return <section className="tournament-phase-results" aria-live="polite">
    <header><span>ETAPA COMPLETADA</span><h2>{PHASES[phase] || phase}: resultados oficiales</h2>
      <p>La clasificación se conserva en pantalla hasta que el administrador autorice el avance.</p></header>
    {phase === 'GROUP' ? <p className="tournament-phase-results-note">Revisa la clasificación oficial por grupo. Los dos primeros lugares avanzan cuando el desempate reglamentario esté resuelto.</p>
      : <div className="tournament-phase-result-list">{matches.map((match) => {
        const winner = match.winner_team_id === match.team_id_a ? match.team_a
          : match.winner_team_id === match.team_id_b ? match.team_b : 'Resultado sin ganador';
        return <article key={match.match_id}><span>{match.bracket_slot || `Encuentro ${match.match_number}`}</span>
          <b>{winner}</b><small>{match.team_a} {match.score_a}–{match.score_b} {match.team_b}</small></article>;
      })}</div>}
    {tournament.can_advance && <div className="tournament-phase-waiting">Fase siguiente preparada: <b>{PHASES[tournament.next_phase] || tournament.next_phase}</b>. En espera de la autorización del administrador.</div>}
    {tournament.unresolved_qualifying_ties?.length > 0 && <div className="tournament-phase-waiting is-warning">Hay empates de clasificación pendientes de resolución reglamentaria.</div>}
  </section>;
}

export default function TorneoEnVivo({ tournament, eventName }) {
  const [fullscreen, setFullscreen] = useState(false);
  const podiumRef = useRef(null);
  useEffect(() => {
    const sync = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);
  const phase = tournament?.phase || 'GROUP';
  const boards = tournament?.boards || [];
  const phaseMatches = (tournament?.matches || []).filter((match) => match.stage_code === phase);
  const dohyoCount = phase === 'GROUP' ? Math.max(1, Math.min(Object.keys(tournament?.groups || {}).length, 4))
    : Math.max(1, Math.min(phaseMatches.length || boards.filter((board) => board.match).length, 4));
  const visibleBoards = boards.filter((board) => board.dohyo_number <= dohyoCount);
  const finalMatch = tournament?.matches?.find((match) => match.stage_code === 'FINAL');
  const champion = phase === 'FINISHED' && finalMatch?.winner_team_id === finalMatch?.team_id_a ? finalMatch?.team_a
    : phase === 'FINISHED' && finalMatch?.winner_team_id === finalMatch?.team_id_b ? finalMatch?.team_b : null;
  const toggleFullscreen = async () => {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.querySelector('.tournament-live-page')?.requestFullscreen(); }
    catch { /* El navegador puede bloquear la API de pantalla completa. */ }
  };
  const togglePodiumFullscreen = async () => {
    if (!podiumRef.current) return;
    if (document.fullscreenElement === podiumRef.current) await document.exitFullscreen();
    else await podiumRef.current.requestFullscreen();
  };

  return <main className={`tournament-live-page ${fullscreen ? 'fullscreen' : ''}`}>
    <header className="tournament-live-header"><div><span>UTA SUMO · TRANSMISIÓN OFICIAL</span><h1>{eventName || 'UTA SUMO ROBOTICS CUP'}</h1>
      <p>{PHASES[phase] || phase} · {dohyoCount || 1} dohyo{dohyoCount === 1 ? '' : 's'} · marcador sincronizado en tiempo real</p></div>
      <div className="tournament-live-tools"><span className={`tournament-live-pill ${phase === 'FINISHED' ? 'finished' : ''}`}><i /> {phase === 'FINISHED' ? 'TORNEO FINALIZADO' : tournament.phase_progress?.complete ? 'FASE COMPLETADA' : 'EN VIVO'}</span>
        <button type="button" onClick={toggleFullscreen}>{fullscreen ? 'Salir de pantalla completa' : '⛶ Pantalla completa'}</button></div></header>
    <TournamentPhaseTransition tournament={tournament} audience="public" />
    <section className="tournament-live-grid" aria-label="Combates simultáneos">{visibleBoards.map((board) => <CombatCard key={board.dohyo_number} board={board} />)}</section>
    {phase === 'GROUP' && <section className="tournament-live-standings"><header><span>CLASIFICACIÓN OFICIAL</span><h2>Posiciones por grupo</h2>
      <p>Orden calculado por el backend: victorias · diferencia de Yukos · duelo directo.</p></header>
      {tournament.phase_progress?.complete && <div className="tournament-standings-complete">Todos los encuentros de grupos finalizaron. {tournament.unresolved_qualifying_ties?.length ? 'Hay desempates reglamentarios pendientes.' : 'La clasificación oficial espera el avance administrativo.'}</div>}
      <div className="tournament-live-groups">{Object.entries(tournament.groups || {}).map(([group, teams]) => <article key={group}>
        <h3>{tournament.group_names?.[group] || `Grupo ${group}`} <small>{tournament.phase_progress?.complete ? 'Clasificación oficial' : 'Posición provisional'}</small></h3>
        <table><thead><tr><th>#</th><th>Equipo / robot</th><th>J</th><th>G</th><th>P</th><th>Yukos +/−</th><th>Estado</th></tr></thead><tbody>
          {teams.map((team) => {
            const unresolved = team.tie_status === 'UNRESOLVED' && team.rank <= 2;
            const status = unresolved ? 'Desempate pendiente' : tournament.phase_progress?.complete
              ? team.rank <= 2 ? 'Clasificado' : 'No clasifica' : team.rank <= 2 ? 'En zona' : 'Pendiente';
            return <tr key={team.team_id} className={team.rank <= 2 ? 'is-qualifier' : ''}>
              <td>{team.rank}</td><td><b>{team.team}</b><small>{team.robot}</small></td><td>{team.played}</td><td>{team.wins}</td><td>{team.losses}</td>
              <td>{team.yukos_for}–{team.yukos_against} ({team.difference > 0 ? '+' : ''}{team.difference})</td><td><span className={`qualification-status ${unresolved ? 'pending' : tournament.phase_progress?.complete && team.rank <= 2 ? 'qualified' : ''}`}>{status}</span></td>
            </tr>;
          })}
        </tbody></table></article>)}</div>
    </section>}
    {phase !== 'GROUP' && <PhaseResults tournament={tournament} phase={phase} />}
    {champion && <section className="tournament-live-champion"><span>CAMPEÓN · RESULTADO CONFIRMADO</span><strong>{champion}</strong>
      <small>Final · {finalMatch.score_a}–{finalMatch.score_b}{finalMatch.loser_team_id ? ` · Segundo lugar: ${finalMatch.loser_team_id === finalMatch.team_id_a ? finalMatch.team_a : finalMatch.team_b}` : ''}</small>
      {tournament.matches?.some((match) => match.stage_code === 'THIRD_PLACE' && match.winner_team_id) && (() => {
        const bronze = tournament.matches.find((match) => match.stage_code === 'THIRD_PLACE' && match.winner_team_id);
        return <small>Tercer lugar: {bronze.winner_team_id === bronze.team_id_a ? bronze.team_a : bronze.team_b}</small>;
      })()}
    </section>}
    {tournament.podium?.length > 0 && <section ref={podiumRef} className="tournament-live-podium"><header><span>🏆 PODIO OFICIAL</span><button type="button" onClick={togglePodiumFullscreen}>⛶ Pantalla completa</button></header><div>{tournament.podium.map((entry) => <article key={entry.position}><b>{entry.position === 1 ? '🏆' : entry.position === 2 ? '🥈' : '🥉'}</b><span>{entry.position === 1 ? '1.º LUGAR OFICIAL' : entry.position === 2 ? '2.º LUGAR OFICIAL' : '3.º LUGAR OFICIAL'}</span><strong>{entry.team}</strong><small>{entry.robot}</small></article>)}</div></section>}
    <div className="tournament-live-sync">Marcador y fase publicados por el servidor. Esta pantalla se actualiza automáticamente.</div>
  </main>;
}
