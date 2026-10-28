import { useEffect, useState, useRef } from 'react';
import {
  obtenerResultadosTorneo,
  EVENTO_RESULTADOS_ACTUALIZADOS,
  suscribirBroadcastChannel,
  suscribirWebSocketCombate,
  iniciarPolling,
  obtenerTablaPosiciones,
} from './services/resultadosApi';
import TorneoEnVivo from './TorneoEnVivo';
import './Resultados.css';

function FullscreenPanel({ className = '', label, children }) {
  const panelRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const syncFullscreen = () => setIsFullscreen(document.fullscreenElement === panelRef.current);
    document.addEventListener('fullscreenchange', syncFullscreen);
    return () => document.removeEventListener('fullscreenchange', syncFullscreen);
  }, []);

  async function toggleFullscreen() {
    const panel = panelRef.current;
    if (!panel) return;
    try {
      if (document.fullscreenElement === panel) await document.exitFullscreen();
      else {
        if (document.fullscreenElement) await document.exitFullscreen();
        await panel.requestFullscreen();
      }
    } catch (error) {
      console.error(`No se pudo cambiar a pantalla completa (${label}):`, error);
    }
  }

  return <section ref={panelRef} className={`live-view-panel ${className} ${isFullscreen ? 'is-panel-fullscreen' : ''}`}>
    <button type="button" className="btn-fullscreen-toggle" onClick={toggleFullscreen}
      title={isFullscreen ? `Salir de pantalla completa: ${label}` : `Pantalla completa: ${label}`}>
      {isFullscreen ? 'Salir de pantalla completa' : '⛶ Pantalla completa'}
    </button>
    {children}
  </section>;
}

export default function Resultados() {
  const [combate, setCombate] = useState(null);
  const [posiciones, setPosiciones] = useState([]);
  const [errorPosiciones, setErrorPosiciones] = useState('');
  const [cargando, setCargando] = useState(true);

  // Estados del Cronómetro (3:00 estándar de sumo)
  const [tiempoRestante, setTiempoRestante] = useState(180);
  const [duracionCronometro, setDuracionCronometro] = useState(180);
  const [direccionCronometro, setDireccionCronometro] = useState('DOWN');
  const [estadoCronometro, setEstadoCronometro] = useState('STOPPED');
  const [cronometroHabilitado, setCronometroHabilitado] = useState(false);
  const [cronometroCorriendo, setCronometroCorriendo] = useState(false);

  // Estados de Animaciones
  const [animandoEspadas, setAnimandoEspadas] = useState(false);
  const [celebrandoGanador, setCelebrandoGanador] = useState(null); // Robot ganador

  const ultimoEstadoRef = useRef('');
  const ultimoGanadorRef = useRef('');

  useEffect(() => {
    const eventId = combate?.event_id;
    if (!eventId) {
      setPosiciones([]);
      return undefined;
    }
    let alive = true;
    const loadStandings = async () => {
      try {
        const rows = await obtenerTablaPosiciones(eventId);
        if (alive) {
          setPosiciones(rows);
          setErrorPosiciones('');
        }
      } catch (error) {
        if (alive) setErrorPosiciones(error.message || 'No se pudo cargar la tabla de posiciones.');
      }
    };
    loadStandings();
    const timer = window.setInterval(loadStandings, 4000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [combate?.event_id, combate?.robotA?.puntos, combate?.robotB?.puntos, combate?.estado]);

  const activarAnimacionEspadas = () => {
    setAnimandoEspadas(true);
    setTimeout(() => {
      setAnimandoEspadas(false);
    }, 2400);
  };

  const activarCelebracionGanador = (nombreRobot) => {
    setCelebrandoGanador(nombreRobot);
  };

  const formatTiempo = (segundos) => {
    const min = Math.floor(segundos / 60);
    const seg = segundos % 60;
    return `${min.toString().padStart(2, '0')}:${seg.toString().padStart(2, '0')}`;
  };

  // ─── SINCRONIZACIÓN EN TIEMPO REAL (3 capas) ──────────────────────────────
  useEffect(() => {
    let activo = true;

    /**
     * Función central que procesa los nuevos datos del combate y dispara
     * las animaciones correspondientes (inicio de combate, declaración ganador).
     */
    function procesarDatosCombate(res) {
      if (!activo) return;

      setCombate(res);
      setCargando(false);
      if (res.cronometro) {
        setCronometroHabilitado(Boolean(res.cronometro.enabled));
        setDuracionCronometro(Math.max(1, Number(res.cronometro.duration_seconds ?? 180)));
        setDireccionCronometro(res.cronometro.direction === 'UP' ? 'UP' : 'DOWN');
        setTiempoRestante(Math.max(0, Number(res.cronometro.current_seconds ?? res.cronometro.remaining_seconds ?? 180)));
        setEstadoCronometro(res.cronometro.status || 'STOPPED');
        setCronometroCorriendo(res.cronometro.status === 'RUNNING' && Boolean(res.cronometro.enabled));
      }

      // Animación de espadas al iniciar el combate
      if (res.estado === 'En combate' && ultimoEstadoRef.current !== 'En combate') {
        activarAnimacionEspadas();
      }
      ultimoEstadoRef.current = res.estado;

      // Animación de victoria cuando se declara un ganador
      if (
        res.ganador &&
        res.ganador !== 'No definido' &&
        res.ganador !== 'Empate' &&
        res.estado === 'Finalizado' &&
        res.ganador !== ultimoGanadorRef.current
      ) {
        ultimoGanadorRef.current = res.ganador;
        activarCelebracionGanador(res.ganador);
      }
    }

    // CAPA 0: Carga inicial de datos
    async function cargarInicial() {
      try {
        const res = await obtenerResultadosTorneo();
        procesarDatosCombate(res);
      } catch (err) {
        console.error('Error al cargar combate en vivo:', err);
        if (activo) setCargando(false);
      }
    }

    cargarInicial();

    // CAPA 1: BroadcastChannel — actualización instantánea entre pestañas del mismo
    // dispositivo (admin en una pestaña, pantalla gigante en otra → < 10ms).
    const { destroy: destroyBroadcast } = suscribirBroadcastChannel((datos) => {
      procesarDatosCombate(datos);
    });

    // El WebSocket del backend difunde cambios entre navegadores/dispositivos.
    // El polling permanece como respaldo si la conexión no está disponible.
    const { stop: stopWebSocket } = suscribirWebSocketCombate((datos) => {
      procesarDatosCombate(datos);
    });

    // CAPA 2: Evento DOM — misma pestaña (disparado por guardarResultadosTorneo).
    const handleEventoDom = (evento) => {
      // CustomEvent con detail lleva los datos ya cargados; evita una nueva lectura de localStorage.
      if (evento.detail) {
        procesarDatosCombate(evento.detail);
      } else {
        // Compatibilidad con Event básico (versiones anteriores)
        obtenerResultadosTorneo().then(procesarDatosCombate).catch(() => {});
      }
    };

    window.addEventListener(EVENTO_RESULTADOS_ACTUALIZADOS, handleEventoDom);

    // CAPA 3: Evento 'storage' del navegador — detecta cambios en localStorage
    // hechos desde otra pestaña en navegadores que no soporten BroadcastChannel.
    const handleStorage = (e) => {
      if (e.key === 'uta.torneo.resultados' && e.newValue) {
        try {
          const datos = JSON.parse(e.newValue);
          if (datos.robotA && datos.robotB) {
            procesarDatosCombate(datos);
          }
        } catch { /* parseo fallido, lo ignora */ }
      }
    };

    window.addEventListener('storage', handleStorage);

    // CAPA 4: Polling inteligente — sincroniza entre DISPOSITIVOS distintos
    // (admin en laptop, pantalla gigante en TV conectada a otro PC/tablet).
    // Intervalo: 2 s cuando visible, 8 s cuando en background.
    const { stop: stopPolling } = iniciarPolling((datos) => {
      procesarDatosCombate(datos);
    });

    return () => {
      activo = false;
      destroyBroadcast();
      stopWebSocket();
      window.removeEventListener(EVENTO_RESULTADOS_ACTUALIZADOS, handleEventoDom);
      window.removeEventListener('storage', handleStorage);
      stopPolling();
    };
  }, []);

  // Lógica del Cronómetro (cuenta regresiva de 3 minutos)
  useEffect(() => {
    let intervalo = null;
    const dentroDelRango = direccionCronometro === 'UP'
      ? tiempoRestante < duracionCronometro
      : tiempoRestante > 0;
    if (cronometroCorriendo && dentroDelRango) {
      intervalo = setInterval(() => {
        setTiempoRestante((prev) => direccionCronometro === 'UP'
          ? Math.min(duracionCronometro, prev + 1)
          : Math.max(0, prev - 1));
      }, 1000);
    }
    return () => {
      if (intervalo) clearInterval(intervalo);
    };
  }, [cronometroCorriendo, tiempoRestante, direccionCronometro, duracionCronometro]);

  if (cargando || !combate) {
    return (
      <div className="live-scoreboard-page">
        <div className="live-loading-box">
          <span className="live-dot-pulse" />
          <p>Conectando con el dohyo oficial y cargando marcador en vivo...</p>
        </div>
      </div>
    );
  }

  if (combate.tournament && combate.tournament.phase !== 'NOT_CONFIGURED') {
    return <TorneoEnVivo tournament={combate.tournament} eventName={combate.event_name || combate.torneo} />;
  }

  const esGanadorA = combate.ganador && combate.ganador !== 'No definido' && combate.ganador === combate.robotA.nombre;
  const esGanadorB = combate.ganador && combate.ganador !== 'No definido' && combate.ganador === combate.robotB.nombre;

  return (
    <div className="live-scoreboard-page">
      {/* ========================================================
          ANIMACIÓN DE ESPADAS CHOCANDO AL INICIAR COMBATE
          ======================================================== */}
      {animandoEspadas && (
        <div className="swords-clash-overlay" onClick={() => setAnimandoEspadas(false)} role="presentation">
          <div className="swords-clash-container">
            <div className="sword-left">🗡️</div>
            <div className="clash-spark-burst" />
            <div className="sword-right">⚔️</div>
          </div>
          <div className="clash-text-banner">
            <h2>¡INICIA EL COMBATE!</h2>
            <p>Dohyo de Robótica UTA Sumo 2026</p>
          </div>
        </div>
      )}

      {/* ========================================================
          ANIMACIÓN CELEBRACIÓN DE GANADOR EN TIEMPO REAL
          ======================================================== */}
      {celebrandoGanador && (
        <div className="winner-celebration-overlay" onClick={() => setCelebrandoGanador(null)} role="dialog" aria-modal="true">
          <div className="confetti-rain">
            {Array.from({ length: 40 }).map((_, i) => (
              <span key={`confetti-${i}`} className={`confetti-piece piece-${i % 6}`} style={{ left: `${(i * 2.5) % 100}%`, animationDelay: `${(i * 0.08) % 2}s` }} />
            ))}
          </div>

          <div className="winner-announcement-card" onClick={(e) => e.stopPropagation()}>
            <span className="winner-trophy-giant">🏆</span>
            <span className="winner-kicker">¡VICTORIA OFICIAL!</span>
            <h2 className="winner-robot-title">{celebrandoGanador}</h2>
            <p className="winner-inst-text">
              {celebrandoGanador === combate.robotA.nombre ? combate.robotA.institucion : combate.robotB.institucion}
            </p>
            <div className="winner-score-recap">
              Marcador Final: {combate.robotA.puntos} - {combate.robotB.puntos}
            </div>
            <button
              type="button"
              className="btn-dismiss-celebration"
              onClick={() => setCelebrandoGanador(null)}
            >
              Ver Marcador Completo →
            </button>
          </div>
        </div>
      )}

      {/* ========================================================
          TARJETA MASIVA PRINCIPAL DEL MARCADOR
          ======================================================== */}
      <FullscreenPanel className="combat-fullscreen-panel" label="marcador y combate">
      <main className="live-scoreboard-card" aria-label="Marcador Oficial del Torneo">
        {/* CABECERA: TÍTULO INSTITUCIONAL Y BADGE EN VIVO */}
        <header className="scoreboard-header">
          <div className="live-indicator-wrap">
            <span className="live-badge-glow">
              <span className="live-dot-pulse" />
              EN VIVO
            </span>
            <button
              type="button"
              className="btn-trigger-swords"
              onClick={activarAnimacionEspadas}
              title="Reproducir animación de choque de combate"
            >
              ⚔️ Inicio de Combate
            </button>
          </div>

          <h1 className="live-event-title">
            Torneo de Robótica <span className="highlight-gold">UTA Sumo 2026</span>
          </h1>
          <p className="live-event-sub">
            {combate.edicion} · {combate.categoria}
          </p>
        </header>

        {/* MARCADOR PRINCIPAL GIGANTE: [ROBOT A] VS [ROBOT B] (SIN DEFORMACIONES) */}
        <section className="scoreboard-arena-row" aria-label="Combate en curso">
          {/* ESQUINA ROJA (ROBOT A) */}
          <article className={`corner-box red-corner ${esGanadorA ? 'is-winner' : ''}`}>
            <div className="corner-tag red-tag">ESQUINA ROJA</div>

            <div className="corner-robot-info">
              <h2 className="giant-robot-name" title={combate.robotA.nombre}>
                {combate.robotA.nombre}
                {esGanadorA && <span className="giant-crown" title="Ganador"> 🏆</span>}
              </h2>
              <p className="giant-robot-inst" title={combate.robotA.institucion}>
                {combate.robotA.institucion || 'Sin institución registrada'}
              </p>
            </div>

            <div className="giant-score-display" aria-label={`Puntos de ${combate.robotA.nombre}`}>
              {combate.robotA.puntos}
            </div>
          </article>

          {/* DIVISOR CENTRAL: VS, ESTADO Y CRONÓMETRO DE COMBATE */}
          <div className="scoreboard-center-hub">
            <span className="giant-vs-text">VS</span>

            {/* CRONÓMETRO OFICIAL DE COMBATE */}
            {cronometroHabilitado ? <div className={`combat-timer-box ${estadoCronometro === 'FINISHED' || (direccionCronometro === 'DOWN' ? tiempoRestante === 0 : tiempoRestante >= duracionCronometro) ? 'timer-ended' : ''}`}>
              <div className="timer-header-label">⏱️ CRONÓMETRO</div>
              <div className="timer-digits">{formatTiempo(tiempoRestante)}</div>
              <div className="timer-server-status" aria-live="polite">
                {cronometroCorriendo && (direccionCronometro === 'DOWN' ? tiempoRestante > 0 : tiempoRestante < duracionCronometro)
                  ? `EN MARCHA · ${direccionCronometro === 'UP' ? 'PROGRESIVO' : 'REGRESIVO'}`
                  : estadoCronometro === 'FINISHED' || (direccionCronometro === 'DOWN' ? tiempoRestante === 0 : tiempoRestante >= duracionCronometro)
                    ? 'TIEMPO FINALIZADO'
                    : 'EN PAUSA'}
              </div>
            </div> : <div className="combat-timer-box timer-disabled-label">CRONÓMETRO DESACTIVADO</div>}

            <span className={`match-state-badge state-${combate.estado.toLowerCase().replace(/\s+/g, '-')}`}>
              {combate.estado}
            </span>

            {combate.ganador && combate.ganador !== 'No definido' && (
              <div className="winner-pill-announcement" onClick={() => activarCelebracionGanador(combate.ganador)} style={{ cursor: 'pointer' }}>
                🏆 Ganador: <strong>{combate.ganador}</strong>
              </div>
            )}
          </div>

          {/* ESQUINA AZUL (ROBOT B) */}
          <article className={`corner-box blue-corner ${esGanadorB ? 'is-winner' : ''}`}>
            <div className="corner-tag blue-tag">ESQUINA AZUL</div>

            <div className="corner-robot-info">
              <h2 className="giant-robot-name" title={combate.robotB.nombre}>
                {esGanadorB && <span className="giant-crown" title="Ganador">🏆 </span>}
                {combate.robotB.nombre}
              </h2>
              <p className="giant-robot-inst" title={combate.robotB.institucion}>
                {combate.robotB.institucion || 'Sin institución registrada'}
              </p>
            </div>

            <div className="giant-score-display" aria-label={`Puntos de ${combate.robotB.nombre}`}>
              {combate.robotB.puntos}
            </div>
          </article>
        </section>

        {/* FOOTER DEL MARCADOR: NOTAS Y SINCRONIZACIÓN (SIN REFERENCIAS A LLAVES) */}
        <footer className="scoreboard-footer">
          <span className="live-detail-note">
            ⚡ {combate.detalles || 'Enfrentamiento oficial en el dohyo de robótica.'}
          </span>
          <span className="live-sync-time">
            Última actualización de jueces: <strong>{combate.ultimaActualizacion}</strong>
          </span>
        </footer>
      </main>
      </FullscreenPanel>
      {combate.event_id && <FullscreenPanel className="standings-fullscreen-panel" label="tabla de posiciones">
      <section className="live-standings-card" aria-labelledby="live-standings-title">
        <header className="live-standings-header">
          <div><span>CLASIFICACIÓN OFICIAL</span><h2 id="live-standings-title">Tabla de posiciones</h2></div>
          <small>Se actualiza automáticamente con los puntos registrados.</small>
        </header>
        {errorPosiciones ? <p className="live-standings-message" role="status">{errorPosiciones}</p>
          : posiciones.length === 0 ? <p className="live-standings-message">Aún no hay equipos aprobados con puntos para mostrar.</p>
            : <div className="live-standings-scroll"><table className="live-standings-table">
              <thead><tr><th>#</th><th>Equipo</th><th>Categoría</th><th>Puntos</th></tr></thead>
              <tbody>{posiciones.map((row) => <tr key={`${row.category_id}-${row.team_id}`}>
                <td>{row.rank}</td><td>{row.team}</td><td>{row.category}</td><td>{row.points}</td>
              </tr>)}</tbody>
            </table></div>}
      </section>
      </FullscreenPanel>}
    </div>
  );
}
