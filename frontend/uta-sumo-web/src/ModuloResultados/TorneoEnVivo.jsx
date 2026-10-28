import { useEffect, useState } from 'react';
import './TorneoEnVivo.css';

const PHASES = { GROUP: 'Fase de grupos', QUARTERFINAL: 'Cuartos de final', SEMIFINAL: 'Semifinales', THIRD_PLACE: 'Combate por el tercer puesto', FINAL: 'Gran final', FINISHED: 'Torneo finalizado' };
const PHASES_SMALL = { GROUP: 'GRUPO', QUARTERFINAL: 'CUARTOS', SEMIFINAL: 'SEMIFINAL', THIRD_PLACE: '3.º / 4.º LUGAR', FINAL: 'GRAN FINAL' };

function CombatCard({ board }) {
  const match = board.match;
  if (!match) return <article className="tournament-live-court is-empty"><header><span>DOHYO {board.dohyo_number}</span><b>En espera</b></header><div>El administrador aún no ha seleccionado el siguiente encuentro.</div></article>;
  const aWinner = match.winner_team_id === match.team_id_a;
  const bWinner = match.winner_team_id === match.team_id_b;
  return <article className={`tournament-live-court ${match.status === 'FINISHED' ? 'is-finished' : ''}`}>
    <header><div><span>DOHYO {board.dohyo_number} · {PHASES_SMALL[match.stage_code] || match.stage_code}{match.group_code ? ` · GRUPO ${match.group_code}` : ''}</span><h2>{match.bracket_slot || `Encuentro ${match.match_number}`}</h2></div><b className={match.status === 'LIVE' ? 'live' : ''}>{match.status === 'LIVE' ? 'EN VIVO' : match.status === 'FINISHED' ? 'FINALIZADO' : 'PROGRAMADO'}</b></header>
    <div className={`tournament-live-side red ${aWinner ? 'winner' : ''}`}><div><small>ESQUINA ROJA</small><strong>{match.robot_a}</strong><span>{match.team_a}</span><em>{match.institution_a || 'Institución no registrada'}</em></div><b>{match.score_a}</b></div>
    <div className="tournament-live-vs">VS</div>
    <div className={`tournament-live-side blue ${bWinner ? 'winner' : ''}`}><div><small>ESQUINA AZUL</small><strong>{match.robot_b}</strong><span>{match.team_b}</span><em>{match.institution_b || 'Institución no registrada'}</em></div><b>{match.score_b}</b></div>
    <footer><span>{match.status === 'FINISHED' ? `🏆 Ganador: ${aWinner ? match.team_a : match.team_b}` : `Primero a ${match.score_to_win} Yukos`}</span><span>{match.status === 'LIVE' ? 'Puntaje actualizado en vivo' : match.status === 'FINISHED' ? 'Resultado confirmado' : 'Siguiente combate'}</span></footer>
  </article>;
}

export default function TorneoEnVivo({ tournament, eventName }) {
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);
  const phase = tournament?.phase || 'GROUP';
  const boards = tournament?.boards || [];
  const finalMatch = tournament?.matches?.find((match) => match.stage_code === 'FINAL');
  const champion = finalMatch?.winner_team_id === finalMatch?.team_id_a ? finalMatch?.team_a
    : finalMatch?.winner_team_id === finalMatch?.team_id_b ? finalMatch?.team_b : null;
  const toggleFullscreen = async () => {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.querySelector('.tournament-live-page')?.requestFullscreen(); }
    catch { /* El navegador puede bloquear la API de pantalla completa. */ }
  };

  return <main className={`tournament-live-page ${fullscreen ? 'fullscreen' : ''}`}>
    <header className="tournament-live-header"><div><span>UTA SUMO · TRANSMISIÓN OFICIAL</span><h1>{eventName || 'UTA SUMO ROBOTICS CUP'}</h1><p>{PHASES[phase] || phase} · cuatro dohyos · marcador sincronizado en tiempo real</p></div>
      <div className="tournament-live-tools"><span className="tournament-live-pill"><i /> {phase === 'FINISHED' ? 'TORNEO FINALIZADO' : 'EN VIVO'}</span><button type="button" onClick={toggleFullscreen}>{fullscreen ? 'Salir de pantalla completa' : '⛶ Pantalla completa'}</button></div></header>
    <section className="tournament-live-grid" aria-label="Combates en los cuatro dohyos">{boards.map((board) => <CombatCard key={board.dohyo_number} board={board} />)}</section>
    {phase === 'GROUP' && <section className="tournament-live-standings"><header><span>CLASIFICACIÓN OFICIAL</span><h2>Posiciones por grupo</h2><p>Victorias · diferencia de Yukos · duelo directo</p></header><div className="tournament-live-groups">{Object.entries(tournament.groups || {}).map(([group, teams]) => <article key={group}><h3>Grupo {group} <small>Top 2 clasifica</small></h3><table><thead><tr><th>#</th><th>Equipo / robot</th><th>J</th><th>G</th><th>P</th><th>Yukos +/−</th></tr></thead><tbody>{teams.map((team) => <tr key={team.team_id}><td>{team.rank}</td><td><b>{team.team}</b><small>{team.robot}</small></td><td>{team.played}</td><td>{team.wins}</td><td>{team.losses}</td><td>{team.yukos_for}–{team.yukos_against} ({team.difference > 0 ? '+' : ''}{team.difference})</td></tr>)}</tbody></table></article>)}</div></section>}
    {champion && <section className="tournament-live-champion"><span>CAMPEÓN</span><strong>{champion}</strong><small>Final · {finalMatch.score_a}–{finalMatch.score_b}</small></section>}
    <div className="tournament-live-sync">La pantalla recibe automáticamente cada Yuko, ganador y cambio de fase.</div>
  </main>;
}
