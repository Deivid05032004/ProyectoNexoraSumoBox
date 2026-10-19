import { useEffect, useState, useRef } from 'react';
import {
  obtenerResultadosTorneo,
  EVENTO_RESULTADOS_ACTUALIZADOS,
  suscribirBroadcastChannel,
  iniciarPolling,
} from './services/resultadosApi';
import './Resultados.css';

export default function Resultados() {
  const [combate, setCombate] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Estados del Cronómetro (3:00 estándar de sumo)
  const [tiempoRestante, setTiempoRestante] = useState(180);
  const [cronometroCorriendo, setCronometroCorriendo] = useState(true);

  // Estados de Animaciones
  const [animandoEspadas, setAnimandoEspadas] = useState(false);
  const [celebrandoGanador, setCelebrandoGanador] = useState(null); // Robot ganador

  const containerRef = useRef(null);
  const ultimoEstadoRef = useRef('');
  const ultimoGanadorRef = useRef('');

  const toggleFullscreen = () => {
    const elem = containerRef.current || document.documentElement;
    if (!document.fullscreenElement) {
      if (elem.requestFullscreen) {
        elem.requestFullscreen().catch(() => {});
      } else if (elem.webkitRequestFullscreen) {
        elem.webkitRequestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
    }
  };

  const activarAnimacionEspadas = () => {
    setAnimandoEspadas(true);
    setTimeout(() => {
      setAnimandoEspadas(false);
    }, 2400);
  };

  const activarCelebracionGanador = (nombreRobot) => {
    setCelebrandoGanador(nombreRobot);
  };

  const reiniciarCronometro = () => {
    setTiempoRestante(180);
    setCronometroCorriendo(combate?.estado === 'En combate');
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

      // Animación de espadas al iniciar el combate
      if (res.estado === 'En combate' && ultimoEstadoRef.current !== 'En combate') {
        activarAnimacionEspadas();
        setCronometroCorriendo(true);
      } else if (res.estado !== 'En combate') {
        setCronometroCorriendo(false);
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
      window.removeEventListener(EVENTO_RESULTADOS_ACTUALIZADOS, handleEventoDom);
      window.removeEventListener('storage', handleStorage);
      stopPolling();
    };
  }, []);

  // Lógica del Cronómetro (cuenta regresiva de 3 minutos)
  useEffect(() => {
    let intervalo = null;
    if (cronometroCorriendo && tiempoRestante > 0) {
      intervalo = setInterval(() => {
        setTiempoRestante((prev) => Math.max(0, prev - 1));
      }, 1000);
    }
    return () => {
      if (intervalo) clearInterval(intervalo);
    };
  }, [cronometroCorriendo, tiempoRestante]);

  // Manejo de Pantalla Completa (Full Screen API)
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    const handleKeyDown = (e) => {
      // Tecla 'F' para alternar pantalla completa
      if ((e.key === 'f' || e.key === 'F') && !e.target.matches('input, textarea, select')) {
        toggleFullscreen();
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

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

  const esGanadorA = combate.ganador && combate.ganador !== 'No definido' && combate.ganador === combate.robotA.nombre;
  const esGanadorB = combate.ganador && combate.ganador !== 'No definido' && combate.ganador === combate.robotB.nombre;

  return (
    <div className={`live-scoreboard-page ${isFullscreen ? 'is-fullscreen-mode' : ''}`} ref={containerRef}>
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
          BOTÓN DE PANTALLA COMPLETA (TIPO YOUTUBE)
          ======================================================== */}
      <button
        type="button"
        className="btn-fullscreen-toggle"
        onClick={toggleFullscreen}
        title={isFullscreen ? 'Salir de pantalla completa (F)' : 'Pantalla completa (F)'}
        aria-label="Alternar pantalla completa"
      >
        {isFullscreen ? (
          /* Icono Minimizar / Salir */
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
          </svg>
        ) : (
          /* Icono Pantalla Completa (Estilo YouTube) */
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
        )}
      </button>

      {/* ========================================================
          TARJETA MASIVA PRINCIPAL DEL MARCADOR
          ======================================================== */}
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
            <div className={`combat-timer-box ${tiempoRestante === 0 ? 'timer-ended' : ''}`}>
              <div className="timer-header-label">⏱️ CRONÓMETRO</div>
              <div className="timer-digits">{formatTiempo(tiempoRestante)}</div>
              <div className="timer-controls-row">
                <button
                  type="button"
                  className="btn-timer-action"
                  onClick={() => setCronometroCorriendo(!cronometroCorriendo)}
                  title={cronometroCorriendo ? 'Pausar cronómetro' : 'Reanudar cronómetro'}
                >
                  {cronometroCorriendo ? '⏸' : '▶'}
                </button>
                <button
                  type="button"
                  className="btn-timer-action"
                  onClick={reiniciarCronometro}
                  title="Reiniciar a 03:00"
                >
                  ↺
                </button>
              </div>
            </div>

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
    </div>
  );
}
