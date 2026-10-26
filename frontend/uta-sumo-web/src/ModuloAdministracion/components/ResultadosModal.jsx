import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiRequest } from '../services/adminApi';
import { obtenerInscripciones } from '../services/adminInscripcionesApi';
import { CRONOMETRO_INICIAL, obtenerConfiguracionCronometro, guardarConfiguracionCronometro } from '../../ModuloResultados/services/resultadosApi';
import './ResultadosModal.css';

function mapRobotRegistration(item) {
  const row = item.raw || {};
  return {
    key: `${row.event_id}:${row.category_id}:${row.team_id}:${row.robot_id}`,
    event_id: Number(row.event_id),
    event_name: row.event_name || `Evento ${row.event_id}`,
    category_id: Number(row.category_id),
    category_name: item.categoria,
    team_id: Number(row.team_id),
    team_name: row.team_name || item.institucion,
    robot_id: Number(row.robot_id),
    robot_name: row.robot_name || item.robot,
    institution_name: item.institucion,
  };
}

function samePair(combat, left, right) {
  return combat?.active && combat.event_id === left.event_id && combat.category_id === left.category_id
    && combat.team_id_a === left.team_id && combat.robot_id_a === left.robot_id
    && combat.team_id_b === right.team_id && combat.robot_id_b === right.robot_id;
}

export default function ResultadosModal({ isOpen, onClose }) {
  const [robots, setRobots] = useState([]);
  const [sideA, setSideA] = useState('');
  const [sideB, setSideB] = useState('');
  const [creatingCombat, setCreatingCombat] = useState(false);
  const [combat, setCombat] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [timerEnabled, setTimerEnabled] = useState(CRONOMETRO_INICIAL.enabled);
  const [timerMinutes, setTimerMinutes] = useState(Math.floor(CRONOMETRO_INICIAL.seconds / 60));
  const [timerSeconds, setTimerSeconds] = useState(CRONOMETRO_INICIAL.seconds % 60);
  const lastPairRef = useRef('');
  const combatRef = useRef(null);

  const robotByKey = useMemo(() => new Map(robots.map((robot) => [robot.key, robot])), [robots]);

  useEffect(() => {
    combatRef.current = combat;
  }, [combat]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [registrations, current] = await Promise.all([
        obtenerInscripciones(),
        apiRequest('/api/v1/competition/combate-actual'),
      ]);
      const approved = registrations
        .filter((item) => item.estado === 'APPROVED')
        .map(mapRobotRegistration)
        .filter((robot) => Number.isFinite(robot.event_id) && Number.isFinite(robot.category_id)
          && Number.isFinite(robot.team_id) && Number.isFinite(robot.robot_id));
      const unique = [...new Map(approved.map((robot) => [robot.key, robot])).values()];
      setRobots(unique);
      setCombat(current);
      combatRef.current = current;
      if (current?.active) {
        const a = unique.find((robot) => robot.event_id === current.event_id && robot.category_id === current.category_id
          && robot.team_id === current.team_id_a && robot.robot_id === current.robot_id_a);
        const b = unique.find((robot) => robot.event_id === current.event_id && robot.category_id === current.category_id
          && robot.team_id === current.team_id_b && robot.robot_id === current.robot_id_b);
        if (a) setSideA(a.key);
        if (b) setSideB(b.key);
      }
      if (!unique.length) setError('No hay robots con inscripción APROBADA disponibles para el marcador.');
    } catch (err) {
      setError(err.message || 'No se pudieron cargar los robots aprobados.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadData();
      const config = obtenerConfiguracionCronometro();
      setTimerEnabled(config.enabled);
      setTimerMinutes(Math.floor(config.seconds / 60));
      setTimerSeconds(config.seconds % 60);
    }
  }, [isOpen, loadData]);

  function saveTimerConfig() {
    const seconds = Math.max(1, Number(timerMinutes || 0) * 60 + Number(timerSeconds || 0));
    guardarConfiguracionCronometro({ enabled: timerEnabled, seconds });
    setNotice(`Cronómetro ${timerEnabled ? 'activado' : 'desactivado'}${timerEnabled ? ` · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : ''}.`);
    setError('');
  }

  const activatePair = useCallback(async (leftKey, rightKey) => {
    const left = robotByKey.get(leftKey);
    const right = robotByKey.get(rightKey);
    if (!left || !right || saving) return;
    if (left.team_id === right.team_id) {
      setError('Selecciona robots de dos equipos distintos.');
      return;
    }
    if (left.event_id !== right.event_id || left.category_id !== right.category_id) {
      setError('Los robots deben pertenecer al mismo evento y categoría.');
      return;
    }
    const pairKey = `${left.key}|${right.key}`;
    if (lastPairRef.current === pairKey) return;
    lastPairRef.current = pairKey;
    setSaving(true);
    setError('');
    setNotice('Preparando combate…');
    try {
      const current = combatRef.current;
      if (samePair(current, left, right)) {
        setNotice('Este combate ya está activo.');
        return;
      }

      // The backend only accepts scores for persisted competition matches. Finish an
      // existing live match before replacing its ActiveCombat pointer.
      if (current?.active && current.match_id && ['EN_VIVO', 'PAUSADO'].includes(current.estado_code)) {
        await apiRequest('/api/v1/competition/combate-actual', {
          method: 'PUT',
          body: JSON.stringify({ match_id: current.match_id, status: 'FINALIZADO' }),
        });
      }

      const roundsResponse = await apiRequest(
        `/api/v1/events/${left.event_id}/rounds?category_id=${left.category_id}&page=1&limit=100`,
      );
      const rounds = roundsResponse.items || [];
      const roundNumber = rounds.reduce((max, round) => Math.max(max, Number(round.round_number) || 0), 0) + 1;
      const round = await apiRequest(`/api/v1/events/${left.event_id}/rounds`, {
        method: 'POST',
        body: JSON.stringify({ category_id: left.category_id, round_number: roundNumber, name: `Marcador manual ${roundNumber}` }),
      });
      const match = await apiRequest(`/api/v1/events/${left.event_id}/matches`, {
        method: 'POST',
        body: JSON.stringify({ round_id: round.id, match_number: 1, team_ids: [left.team_id, right.team_id], robot_ids: [left.robot_id, right.robot_id] }),
      });
      const snapshot = await apiRequest('/api/v1/competition/combate-actual', {
        method: 'PUT',
        body: JSON.stringify({ match_id: match.match_id, status: 'PROGRAMADO' }),
      });
      setCombat(snapshot);
      combatRef.current = snapshot;
      setNotice(`Combate creado como pendiente: ${snapshot.robot_a} vs ${snapshot.robot_b}. Cambia el estado desde el selector del combate.`);
    } catch (err) {
      lastPairRef.current = '';
      setError(err.message || 'No se pudo activar el combate.');
      setNotice('');
    } finally {
      setSaving(false);
    }
  }, [robotByKey, saving]);

  async function createCombat() {
    if (!sideA || !sideB || creatingCombat || saving) return;
    setCreatingCombat(true);
    try {
      await activatePair(sideA, sideB);
    } finally {
      setCreatingCombat(false);
    }
  }

  async function changeCombatStatus(status) {
    const current = combatRef.current;
    if (!current?.match_id || saving || status === current.estado_code) return;
    setSaving(true);
    setError('');
    try {
      const snapshot = await apiRequest('/api/v1/competition/combate-actual', {
        method: 'PUT',
        body: JSON.stringify({ match_id: current.match_id, status }),
      });
      setCombat(snapshot);
      combatRef.current = snapshot;
      setNotice(`Estado del combate actualizado: ${snapshot.estado}.`);
    } catch (err) {
      setError(err.message || 'No se pudo cambiar el estado del combate.');
    } finally { setSaving(false); }
  }

  function handleRobotSelection(side, key) {
    lastPairRef.current = '';
    if (side === 'A') setSideA(key);
    else setSideB(key);
  }

  const updateScore = async (side, delta) => {
    const current = combatRef.current;
    if (!current?.active || !current.match_id || saving) return;
    const scoreA = Math.max(0, Number(current.puntaje_a || 0) + (side === 'A' ? delta : 0));
    const scoreB = Math.max(0, Number(current.puntaje_b || 0) + (side === 'B' ? delta : 0));
    setSaving(true);
    setError('');
    try {
      const snapshot = await apiRequest('/api/v1/competition/combate-actual', {
        method: 'PUT',
        body: JSON.stringify({
          match_id: current.match_id,
          score_a: scoreA,
          score_b: scoreB,
          reason: 'Actualización manual del marcador',
        }),
      });
      setCombat(snapshot);
      combatRef.current = snapshot;
      setNotice(`Marcador sincronizado: ${snapshot.puntaje_a} – ${snapshot.puntaje_b}.`);
    } catch (err) {
      setError(err.message || 'No se pudo sincronizar el puntaje.');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;
  const robotOption = (robot) => `${robot.robot_name} · ${robot.team_name} · ${robot.event_name} / ${robot.category_name}`;
  const active = combat?.active;
  const hasCombat = Boolean(combat?.match_id);

  return <div className="resultados-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="manual-score-title">
    <section className="resultados-modal-container">
      <header className="modal-header">
        <div><span className="modal-badge-live">Marcador en vivo</span><h2 id="manual-score-title">Combate manual</h2>
          <p>Elige dos robots aprobados. La selección crea y activa una ronda/combate en el backend.</p></div>
        <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Cerrar">×</button>
      </header>
      {error && <div className="manual-score-alert" role="alert">{error}</div>}
      {notice && <div className="manual-score-notice" role="status">{notice}</div>}
      {loading ? <div className="table-state-box">Cargando inscripciones aprobadas…</div> : <>
        <div className="modal-body single-match-form">
          <section className="timer-admin-settings" aria-label="Configuración del cronómetro">
            <label className="timer-admin-toggle"><input type="checkbox" checked={timerEnabled} onChange={(event) => setTimerEnabled(event.target.checked)} />
              <span>Usar cronómetro en este combate</span></label>
            <label className="timer-admin-field">Minutos<input type="number" min="0" max="99" value={timerMinutes} disabled={!timerEnabled}
              onChange={(event) => setTimerMinutes(Math.min(99, Math.max(0, Number(event.target.value))))} /></label>
            <label className="timer-admin-field">Segundos<input type="number" min="0" max="59" value={timerSeconds} disabled={!timerEnabled}
              onChange={(event) => setTimerSeconds(Math.min(59, Math.max(0, Number(event.target.value))))} /></label>
            <button type="button" className="btn-modal-secondary" onClick={saveTimerConfig}>Aplicar tiempo</button>
            <small>Se aplica en las pantallas de resultados abiertas en este navegador.</small>
          </section>
          <div className="competitors-duel-form">
            <section className="corner-form-card red-corner-form">
              <div className="corner-header-badge red-badge">Lado A · Esquina roja</div>
              <label className="form-field"><span>Robot aprobado</span><select className="select-combo-quick" value={sideA}
                onChange={(event) => handleRobotSelection('A', event.target.value)} disabled={saving || !robots.length}>
                <option value="">Seleccionar robot…</option>{robots.map((robot) => <option key={robot.key} value={robot.key}>{robotOption(robot)}</option>)}
              </select></label>
              <div className="manual-score-points"><button type="button" className="btn-score-stepper" onClick={() => updateScore('A', -1)} disabled={!active || saving}>−</button>
                <strong>{active ? combat.puntaje_a : 0}</strong><button type="button" className="btn-score-stepper" onClick={() => updateScore('A', 1)} disabled={!active || saving}>+</button></div>
            </section>
            <div className="vs-center-tag">VS</div>
            <section className="corner-form-card blue-corner-form">
              <div className="corner-header-badge blue-badge">Lado B · Esquina azul</div>
              <label className="form-field"><span>Robot aprobado</span><select className="select-combo-quick" value={sideB}
                onChange={(event) => handleRobotSelection('B', event.target.value)} disabled={saving || !robots.length}>
                <option value="">Seleccionar robot…</option>{robots.map((robot) => <option key={robot.key} value={robot.key}>{robotOption(robot)}</option>)}
              </select></label>
              <div className="manual-score-points"><button type="button" className="btn-score-stepper" onClick={() => updateScore('B', -1)} disabled={!active || saving}>−</button>
                <strong>{active ? combat.puntaje_b : 0}</strong><button type="button" className="btn-score-stepper" onClick={() => updateScore('B', 1)} disabled={!active || saving}>+</button></div>
            </section>
          </div>
          <div className="create-combat-action">
            <button type="button" className="btn-create-combat" onClick={createCombat}
              disabled={saving || creatingCombat || !sideA || !sideB}>
              {creatingCombat || saving ? 'Creando combate…' : 'Crear combate'}
            </button>
            <span>Selecciona los dos robots y confirma para crear la ronda y el combate.</span>
          </div>
          {hasCombat && <label className="combat-state-control">Estado
            <select className="combat-state-split" value={combat.estado_code} onChange={(event) => changeCombatStatus(event.target.value)} disabled={saving || ['FINALIZADO', 'CANCELADO'].includes(combat.estado_code)}>
              {combat.estado_code === 'PROGRAMADO' && <><option value="PROGRAMADO">Pendiente</option><option value="EN_VIVO">En combate</option><option value="CANCELADO">Cancelado</option></>}
              {combat.estado_code === 'EN_VIVO' && <><option value="EN_VIVO">En combate</option><option value="PAUSADO">Pausado</option><option value="FINALIZADO">Finalizado</option><option value="CANCELADO">Cancelado</option></>}
              {combat.estado_code === 'PAUSADO' && <><option value="PAUSADO">Pausado</option><option value="EN_VIVO">En combate</option><option value="FINALIZADO">Finalizado</option><option value="CANCELADO">Cancelado</option></>}
              {['FINALIZADO', 'CANCELADO'].includes(combat.estado_code) && <option value={combat.estado_code}>{combat.estado}</option>}
            </select>
          </label>}
          {hasCombat && <p className="manual-score-match">{active ? 'Combate' : 'Último combate'}: <strong>{combat.robot_a}</strong> ({combat.equipo_a}) vs <strong>{combat.robot_b}</strong> ({combat.equipo_b}) · {combat.estado}</p>}
          {!hasCombat && robots.length > 0 && <p className="manual-score-hint">Selecciona un robot en ambos lados para crear el combate.</p>}
        </div>
      </>}
      <footer className="modal-footer"><button type="button" className="btn-modal-secondary" onClick={onClose}>Cerrar</button></footer>
    </section>
  </div>;
}
