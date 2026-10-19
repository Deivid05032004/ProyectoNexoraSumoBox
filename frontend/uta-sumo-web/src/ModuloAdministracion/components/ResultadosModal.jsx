import { useState, useEffect } from 'react';
import {
  obtenerResultadosTorneo,
  guardarResultadosTorneo,
  LISTA_EQUIPOS_OFICIALES,
  EQUIPO_POR_DEFINIR,
} from '../../ModuloResultados/services/resultadosApi';
import './ResultadosModal.css';

export default function ResultadosModal({ isOpen, onClose }) {
  const [combate, setCombate] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [notificacion, setNotificacion] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    async function cargar() {
      const res = await obtenerResultadosTorneo();
      setCombate(JSON.parse(JSON.stringify(res))); // Copia profunda para editar
    }
    cargar();
  }, [isOpen]);

  if (!isOpen || !combate) return null;

  // Selección rápida de robot oficial desde combo box
  const handleQuickSelectRobot = (lado, robotNombre) => {
    const encontrado = LISTA_EQUIPOS_OFICIALES.find((e) => e.nombre === robotNombre) || EQUIPO_POR_DEFINIR;
    setCombate((prev) => {
      const copia = { ...prev };
      copia[lado] = {
        ...copia[lado],
        nombre: encontrado.nombre,
        institucion: encontrado.institucion,
      };

      // Si el ganador anterior ya no coincide, volver a 'No definido'
      if (
        copia.ganador &&
        copia.ganador !== 'No definido' &&
        copia.ganador !== 'Empate' &&
        copia.ganador !== copia.robotA.nombre &&
        copia.ganador !== copia.robotB.nombre
      ) {
        copia.ganador = 'No definido';
      }

      return copia;
    });
  };

  // Edición directa de campos de texto de los robots
  const handleRobotFieldChange = (lado, campo, valor) => {
    setCombate((prev) => ({
      ...prev,
      [lado]: {
        ...prev[lado],
        [campo]: valor,
      },
    }));
  };

  // Cambio de puntuación con botones stepper (+ / -)
  const handlePuntosChange = (lado, delta) => {
    setCombate((prev) => {
      const actual = prev[lado].puntos || 0;
      const nuevo = Math.max(0, actual + delta);
      return {
        ...prev,
        [lado]: {
          ...prev[lado],
          puntos: nuevo,
        },
      };
    });
  };

  // Guardar y transmitir a la pantalla gigante
  const handleGuardar = async (e) => {
    e?.preventDefault();
    setGuardando(true);
    try {
      await guardarResultadosTorneo(combate);
      setNotificacion('¡Combate actualizado y proyectado en pantalla gigante con éxito!');
      setTimeout(() => {
        setNotificacion('');
        onClose();
      }, 1000);
    } catch {
      setNotificacion('Error al guardar el combate.');
    } finally {
      setGuardando(false);
    }
  };

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
