import { useEffect, useRef, useState } from 'react';
import './TournamentPhaseTransition.css';

const LABELS = {
  NOT_CONFIGURED: 'Configuración del torneo', GROUP: 'Fase de grupos',
  ROUND_OF_64: 'Ronda de 64', ROUND_OF_32: 'Ronda de 32',
  ROUND_OF_16: 'Octavos de final', QUARTERFINAL: 'Cuartos de final',
  SEMIFINAL: 'Semifinales', THIRD_PLACE: 'Tercer puesto',
  FINAL: 'Gran final', FINISHED: 'Torneo finalizado',
};

function winningTeam(match) {
  if (match.winner_team_id === match.team_id_a) return match.team_a;
  if (match.winner_team_id === match.team_id_b) return match.team_b;
  return 'Resultado sin ganador';
}

export default function TournamentPhaseTransition({ tournament, audience = 'public' }) {
  const previousSnapshot = useRef(null);
  const [transition, setTransition] = useState(null);

  useEffect(() => {
    if (!tournament?.phase || tournament.phase === 'NOT_CONFIGURED') return;
    const previous = previousSnapshot.current;
    if (previous && previous.phase !== tournament.phase) {
      setTransition({ from: previous, to: tournament });
      previousSnapshot.current = tournament;
      return undefined;
    }
    previousSnapshot.current = tournament;
    return undefined;
  }, [tournament]);

  useEffect(() => {
    if (!transition) return undefined;
    const timeout = window.setTimeout(() => setTransition(null), 5200);
    return () => window.clearTimeout(timeout);
  }, [transition]);

  if (!transition) return null;
  const { from, to } = transition;
  const phaseMatches = (from.matches || []).filter((match) => match.stage_code === from.phase);
  const groupResults = from.phase === 'GROUP'
    ? Object.entries(from.groups || {}) : [];

  return <section className="phase-transition" aria-live="polite" aria-label="Transición de fase">
    <div className="phase-transition-visual" aria-hidden="true"><span /><i>VS</i><span /></div>
    <div className="phase-transition-content">
      <span className="phase-transition-kicker">ETAPA COMPLETADA · RESULTADO OFICIAL</span>
      <h2>{LABELS[from.phase] || from.phase} finalizada</h2>
      <p>{LABELS[to.phase] || to.phase} · {audience === 'admin'
        ? 'La fase nueva está preparada. El control del torneo sigue en manos del administrador.'
        : 'El administrador preparó la siguiente fase de la competencia.'}</p>
      {groupResults.length > 0 ? <div className="phase-transition-groups">
        {groupResults.map(([code, teams]) => <div key={code}>
          <strong>{from.group_names?.[code] || `Grupo ${code}`}</strong>
          <span>{teams.filter((team) => team.rank <= 2).map((team) => team.team).join(' · ') || 'Sin clasificados'}</span>
        </div>)}
      </div> : <ul className="phase-transition-winners">
        {phaseMatches.map((match) => <li key={match.match_id}>
          <span>{match.bracket_slot || `Encuentro ${match.match_number}`}</span>
          <b>{winningTeam(match)}</b>
          <small>{match.score_a}–{match.score_b}</small>
        </li>)}
      </ul>}
      <div className="phase-transition-next"><span aria-hidden="true">✦</span> Siguiente: <b>{LABELS[to.phase] || to.phase}</b></div>
    </div>
  </section>;
}
