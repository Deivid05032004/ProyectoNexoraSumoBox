import { useState, useEffect, useRef, useCallback } from 'react';
import {
  LISTA_EQUIPOS_OFICIALES,
  EQUIPO_POR_DEFINIR,
} from '../../ModuloResultados/services/resultadosApi';
import './ResultadosModal.css';

/**
 * Tiempo de debounce (ms) para publicar cambios de texto mientras el admin escribe.
 * Los steppers de puntos y el ganador publican de forma inmediata.
 */
const DEBOUNCE_PUBLICAR_MS = 700;

export default function ResultadosModal({ isOpen, onClose }) {
  const [combate, setCombate] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [notificacion, setNotificacion] = useState('');
  const [indicadorSync, setIndicadorSync] = useState(''); // '' | 'sincronizando' | 'ok'

  const debounceTimerRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    async function cargar() {
      try {
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/v1/competition/combate-actual`);
        if (!response.ok) throw new Error('Error cargando el combate actual');
        const res = await response.json();
        setCombate(res);
      } catch (error) {
        console.error('Error al cargar el combate actual:', error);
      }
    }
    cargar();
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [isOpen]);

  // ─── PUBLICACIÓN EN TIEMPO REAL ─────────────────────────────────────────
  /**
   * Publica el combate al BroadcastChannel e localStorage.
   * - inmediato=true  → sin debounce (steppers, ganador, estado)
   * - inmediato=false → con debounce (campos de texto mientras se escribe)
   */
  // ─── PUBLICACIÓN EN TIEMPO REAL AL BACKEND ────────────────────────────────

const publicarEnVivo = useCallback((datosCombate, inmediato = false) => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);

    const ejecutar = async () => {
      setIndicadorSync('sincronizando');
      try {
        const token = sessionStorage.getItem('adminToken'); // O donde guardes tu token
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/v1/competition/combate-actual`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(datosCombate)
        });

        if (response.ok) {
          setIndicadorSync('ok');
          setTimeout(() => setIndicadorSync(''), 1400);
        }
      } catch (error) {
        console.error("Error al sincronizar en vivo:", error);
        setIndicadorSync('');
      }
    };

    if (inmediato) {
      ejecutar();
    } else {
      debounceTimerRef.current = setTimeout(ejecutar, DEBOUNCE_PUBLICAR_MS);
    }
  }, []);

  // Botón explícito: cancela debounce, publica una última vez y cierra
  const handleGuardar = async (e) => {
    e?.preventDefault();
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    setGuardando(true);
    try {
      const token = sessionStorage.getItem('adminToken');
      const response = await fetch(`${import.meta.env.VITE_API_URL}/api/v1/competition/combate-actual`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(combate)
      });
      
      if (!response.ok) throw new Error('Error guardando en backend');

      setNotificacion('¡Combate publicado en pantalla gigante con éxito!');
      setTimeout(() => {
        setNotificacion('');
        onClose();
      }, 900);
    } catch (error) {
      console.error("Error al guardar:", error);
      setNotificacion('Error al guardar el combate en el servidor.');
    } finally {
      setGuardando(false);
    }
  };

  // ─── MANEJADORES ────────────────────────────────────────────────────────

  const handleQuickSelectRobot = (lado, robotNombre) => {
    const encontrado = LISTA_EQUIPOS_OFICIALES.find((e) => e.nombre === robotNombre) || EQUIPO_POR_DEFINIR;
    setCombate((prev) => {
      const copia = { ...prev };
      copia[lado] = {
        ...copia[lado],
        nombre: encontrado.nombre,
        institucion: encontrado.institucion,
      };
      if (
        copia.ganador &&
        copia.ganador !== 'No definido' &&
        copia.ganador !== 'Empate' &&
        copia.ganador !== copia.robotA.nombre &&
        copia.ganador !== copia.robotB.nombre
      ) {
        copia.ganador = 'No definido';
      }
      publicarEnVivo(copia);
      return copia;
    });
  };

  // Campos de texto: debounce para no publicar en cada tecla
  const handleRobotFieldChange = (lado, campo, valor) => {
    setCombate((prev) => {
      const nuevo = { ...prev, [lado]: { ...prev[lado], [campo]: valor } };
      publicarEnVivo(nuevo); // con debounce
      return nuevo;
    });
  };

  // Steppers de puntos: publicación INMEDIATA (el juez necesita ver el marcador al instante)
  const handlePuntosChange = (lado, delta) => {
    setCombate((prev) => {
      const nuevo = Math.max(0, (prev[lado].puntos || 0) + delta);
      const actualizado = { ...prev, [lado]: { ...prev[lado], puntos: nuevo } };
      publicarEnVivo(actualizado, true); // inmediato
      return actualizado;
    });
  };

  // Estado del combate: publicación inmediata
  const handleEstadoChange = (nuevoEstado) => {
    setCombate((prev) => {
      const nuevo = { ...prev, estado: nuevoEstado };
      publicarEnVivo(nuevo, true);
      return nuevo;
    });
  };

  // Ganador: publicación inmediata (dispara animación de victoria en /resultados)
  const handleGanadorChange = (nuevoGanador) => {
    setCombate((prev) => {
      const nuevo = {
        ...prev,
        ganador: nuevoGanador,
        estado: nuevoGanador && nuevoGanador !== 'No definido' ? 'Finalizado' : prev.estado,
      };
      publicarEnVivo(nuevo, true);
      return nuevo;
    });
  };

  if (!isOpen || !combate) return null;

  
  const opcionesGanador = [
    'No definido',
    combate.robotA.nombre,
    combate.robotB.nombre,
    'Empate',
  ].filter(Boolean);

  return (
    <div className="resultados-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="resultados-modal-container" onClick={(e) => e.stopPropagation()}>
        {/* HEADER DEL FORMULARIO */}
        <div className="modal-header">
          <div>
            <span className="modal-badge-live">Panel de Jueces Oficial</span>
            <h2>Cargar / Actualizar Combate Actual</h2>
            <p>
              Actualiza los nombres, instituciones y puntajes para proyectarlos inmediatamente en la pantalla gigante de <code>/resultados</code>.
            </p>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Cerrar modal">
            ✕
          </button>
        </div>

        {notificacion && (
          <div className="modal-alert-success" role="status">
            ✓ {notificacion}
          </div>
        )}

        <form onSubmit={handleGuardar} className="modal-body single-match-form">
          {/* SECCIÓN 1: ESTADO DEL COMBATE */}
          <div className="form-section-box">
            <div className="form-field">
              <label>Estado del Combate en Pantalla</label>
              <select
                value={combate.estado}
                onChange={(e) => setCombate({ ...combate, estado: e.target.value })}
                className="select-highlight-state"
              >
                <option value="En combate">🔴 En combate (Activa cronómetro y marcador en vivo)</option>
                <option value="Finalizado">🟢 Finalizado (Habilita declaración de ganador)</option>
                <option value="Pausa técnica">🟡 Pausa técnica / Calentamiento</option>
              </select>
            </div>
          </div>

          {/* SECCIÓN 2: COMPETIDORES Y PUNTUACIÓN */}
          <div className="form-section-box">
            <h3 className="form-section-title">⚔️ Competidores y Puntuación</h3>

            <div className="competitors-duel-form">
              {/* ROBOT A (ESQUINA ROJA) */}
              <div className="corner-form-card red-corner-form">
                <div className="corner-header-badge red-badge">ESQUINA ROJA (ROBOT A)</div>

                <div className="form-field">
                  <label>Selección Rápida Oficial</label>
                  <select
                    value={combate.robotA.nombre}
                    onChange={(e) => handleQuickSelectRobot('robotA', e.target.value)}
                    className="select-combo-quick"
                  >
                    {LISTA_EQUIPOS_OFICIALES.map((eq) => (
                      <option key={`a-${eq.id}-${eq.nombre}`} value={eq.nombre}>
                        {eq.nombre === 'Por definir' ? '⚪ Por definir' : `🤖 ${eq.nombre}`}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-field">
                  <label>Nombre del Robot</label>
                  <input
                    type="text"
                    value={combate.robotA.nombre}
                    onChange={(e) => handleRobotFieldChange('robotA', 'nombre', e.target.value)}
                    required
                    placeholder="Ej. Katana II"
                  />
                </div>

                <div className="form-field">
                  <label>Institución / Club</label>
                  <input
                    type="text"
                    value={combate.robotA.institucion}
                    onChange={(e) => handleRobotFieldChange('robotA', 'institucion', e.target.value)}
                    required
                    placeholder="Ej. UTA · FISEI"
                  />
                </div>

                <div className="score-control-block">
                  <label>Puntos del Robot A</label>
                  <div className="score-buttons-row">
                    <button
                      type="button"
                      className="btn-score-stepper"
                      onClick={() => handlePuntosChange('robotA', -1)}
                      title="Restar 1 punto"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      min="0"
                      max="99"
                      value={combate.robotA.puntos}
                      onChange={(e) => handleRobotFieldChange('robotA', 'puntos', Math.max(0, parseInt(e.target.value, 10) || 0))}
                      className="input-giant-score"
                    />
                    <button
                      type="button"
                      className="btn-score-stepper"
                      onClick={() => handlePuntosChange('robotA', 1)}
                      title="Sumar 1 punto"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>

              <div className="vs-center-tag">VS</div>

              {/* ROBOT B (ESQUINA AZUL) */}
              <div className="corner-form-card blue-corner-form">
                <div className="corner-header-badge blue-badge">ESQUINA AZUL (ROBOT B)</div>

                <div className="form-field">
                  <label>Selección Rápida Oficial</label>
                  <select
                    value={combate.robotB.nombre}
                    onChange={(e) => handleQuickSelectRobot('robotB', e.target.value)}
                    className="select-combo-quick"
                  >
                    {LISTA_EQUIPOS_OFICIALES.map((eq) => (
                      <option key={`b-${eq.id}-${eq.nombre}`} value={eq.nombre}>
                        {eq.nombre === 'Por definir' ? '⚪ Por definir' : `🤖 ${eq.nombre}`}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-field">
                  <label>Nombre del Robot</label>
                  <input
                    type="text"
                    value={combate.robotB.nombre}
                    onChange={(e) => handleRobotFieldChange('robotB', 'nombre', e.target.value)}
                    required
                    placeholder="Ej. Tornado"
                  />
                </div>

                <div className="form-field">
                  <label>Institución / Club</label>
                  <input
                    type="text"
                    value={combate.robotB.institucion}
                    onChange={(e) => handleRobotFieldChange('robotB', 'institucion', e.target.value)}
                    required
                    placeholder="Ej. Colegio La Salle"
                  />
                </div>

                <div className="score-control-block">
                  <label>Puntos del Robot B</label>
                  <div className="score-buttons-row">
                    <button
                      type="button"
                      className="btn-score-stepper"
                      onClick={() => handlePuntosChange('robotB', -1)}
                      title="Restar 1 punto"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      min="0"
                      max="99"
                      value={combate.robotB.puntos}
                      onChange={(e) => handleRobotFieldChange('robotB', 'puntos', Math.max(0, parseInt(e.target.value, 10) || 0))}
                      className="input-giant-score"
                    />
                    <button
                      type="button"
                      className="btn-score-stepper"
                      onClick={() => handlePuntosChange('robotB', 1)}
                      title="Sumar 1 punto"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* SECCIÓN 3: GANADOR Y DETALLES */}
          <div className="form-section-box">
            <h3 className="form-section-title">🏆 Declaración de Ganador y Observaciones</h3>
            <div className="meta-grid-2">
              <div className="form-field">
                <label>Ganador Declarado</label>
                <select
                  value={combate.ganador || 'No definido'}
                  onChange={(e) => {
                    const nuevoGanador = e.target.value;
                    setCombate({
                      ...combate,
                      ganador: nuevoGanador,
                      estado: nuevoGanador && nuevoGanador !== 'No definido' ? 'Finalizado' : combate.estado,
                    });
                  }}
                  className="select-ganador-field"
                >
                  {opcionesGanador.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt === 'No definido' ? '⚪ No definido / En combate' : `🏆 ${opt}`}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-field">
                <label>Observaciones del Asalto (Opcional)</label>
                <input
                  type="text"
                  value={combate.detalles || ''}
                  onChange={(e) => setCombate({ ...combate, detalles: e.target.value })}
                  placeholder="Ej. Definición por salida lateral de dohyo"
                />
              </div>
            </div>
          </div>

          {/* FOOTER DEL FORMULARIO */}
          <div className="modal-footer">
            <button type="button" className="btn-modal-secondary" onClick={onClose} disabled={guardando}>
              Cancelar
            </button>
            <button type="submit" className="btn-modal-primary" disabled={guardando}>
              {guardando ? 'Transmitiendo...' : '⚡ Actualizar y Proyectar en Pantalla Gigante'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
