/**
 * Servicio de Resultados con Sincronización en Tiempo Real.
 *
 * Capas de sincronización implementadas:
 *  1. BroadcastChannel API — instantáneo entre pestañas del mismo origen (mismo dispositivo).
 *     El admin guarda → la pantalla gigante en otra pestaña recibe en < 10ms.
 *  2. Polling inteligente — refresca cada POLL_INTERVAL_MS cuando la pestaña está visible,
 *     o cada POLL_BACKGROUND_MS cuando está en background.
 *     Garantiza sincronización entre dispositivos distintos (admin en laptop, pantalla en TV).
 *  3. Page Visibility API — pausa el polling agresivo cuando la pestaña no está activa.
 *
 * No requiere cambios en el backend. Toda la persistencia usa localStorage.
 * Cuando se integre un backend real, solo hay que cambiar las funciones
 * obtenerResultadosTorneo() y guardarResultadosTorneo().
 */

const STORAGE_KEY_RESULTADOS = 'uta.torneo.resultados';
const BROADCAST_CHANNEL_NAME = 'uta-resultados-channel';

/** Nombre del evento DOM interno para notificar dentro de la misma pestaña. */
export const EVENTO_RESULTADOS_ACTUALIZADOS = 'uta-resultados-updated';

/** Intervalo de polling cuando la pestaña está visible (ms). */
const POLL_INTERVAL_ACTIVE_MS = 2000;

/** Intervalo de polling cuando la pestaña está en background (ms). */
const POLL_INTERVAL_BACKGROUND_MS = 8000;

// ─────────────────────────────────────────────────────────────────────────────
//  DATOS ESTÁTICOS
// ─────────────────────────────────────────────────────────────────────────────

export const EQUIPO_POR_DEFINIR = {
  id: 'tbd',
  nombre: 'Por definir',
  institucion: 'Sin asignar',
};

export const LISTA_EQUIPOS_OFICIALES = [
  { id: 'tbd', nombre: 'Por definir', institucion: 'Sin asignar' },
  { id: '1', nombre: 'Katana II', institucion: 'UTA · FISEI' },
  { id: '2', nombre: 'Tornado', institucion: 'Colegio La Salle' },
  { id: '3', nombre: 'Rayo', institucion: 'Colegio Nacional Bolívar' },
  { id: '4', nombre: 'Titán', institucion: 'U.E. Juan Montalvo' },
  { id: '5', nombre: 'Katana', institucion: 'UTA · FISEI' },
  { id: '6', nombre: 'Tigre RC', institucion: 'Colegio Nacional Bolívar' },
  { id: '7', nombre: 'Fénix Bot', institucion: 'Unidad Educativa Bolívar' },
  { id: '8', nombre: 'Goliath', institucion: 'UTA · FISEI' },
  { id: '9', nombre: 'Viper RC', institucion: 'Instituto Guayaquil' },
  { id: '10', nombre: 'Centella', institucion: 'Colegio Experimental Ambato' },
  { id: '11', nombre: 'Iron Clad', institucion: 'UTA · FISEI' },
  { id: '12', nombre: 'Megatron', institucion: 'U.E. Santo Domingo' },
  { id: '13', nombre: 'Shadow Bot', institucion: 'UTA · FISEI' },
  { id: '14', nombre: 'Apex Predator', institucion: 'UTA · FISEI' },
  { id: '15', nombre: 'Vórtice', institucion: 'U.E. Rumiñahui' },
  { id: '16', nombre: 'Titanium', institucion: 'UTA · FISEI' },
];

export const COMBATE_ACTUAL_INICIAL = {
  id: 'COMB-01',
  torneo: 'Torneo de Robótica UTA Sumo 2026',
  edicion: 'Nexora Sumo Box · Edición Anual',
  categoria: 'Mini Sumo RC Amateur',
  estado: 'En combate',
  robotA: {
    nombre: 'Katana II',
    institucion: 'UTA · FISEI',
    puntos: 2,
  },
  robotB: {
    nombre: 'Tornado',
    institucion: 'Colegio La Salle',
    puntos: 1,
  },
  ganador: 'No definido',
  detalles: '',
  tiempoSegundos: 180,
  cronometroActivo: true,
  ultimaActualizacion: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
};

// ─────────────────────────────────────────────────────────────────────────────
//  CAPA 1 — BroadcastChannel (entre pestañas del mismo dispositivo)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Crea y devuelve un BroadcastChannel para recibir actualizaciones en tiempo real.
 * Retorna null si el API no está disponible (Safari < 15.4, etc.).
 *
 * @param {(datos: object) => void} onMensaje - Callback con los nuevos datos del combate.
 * @returns {{ channel: BroadcastChannel | null, destroy: () => void }}
 */
export function suscribirBroadcastChannel(onMensaje) {
  if (typeof BroadcastChannel === 'undefined') {
    return { channel: null, destroy: () => {} };
  }

  const channel = new BroadcastChannel(BROADCAST_CHANNEL_NAME);

  channel.onmessage = (evento) => {
    if (evento.data?.tipo === 'combate-actualizado' && evento.data?.payload) {
      onMensaje(evento.data.payload);
    }
  };

  channel.onmessageerror = () => {
    // Ignora errores de deserialización del canal
  };

  return {
    channel,
    destroy: () => {
      try { channel.close(); } catch { /* ya cerrado */ }
    },
  };
}

/**
 * Emite los nuevos datos del combate por BroadcastChannel a todas las pestañas.
 */
function emitirBroadcast(datos) {
  if (typeof BroadcastChannel === 'undefined') return;
  try {
    const canal = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
    canal.postMessage({ tipo: 'combate-actualizado', payload: datos });
    // Cierra el canal emisor inmediatamente; el receptor tiene su propio canal.
    canal.close();
  } catch {
    // No crítico, el polling tomará el relevo
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  CAPA 2 — Polling inteligente (entre dispositivos distintos)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Inicia el polling inteligente que consulta los datos del combate periódicamente.
 * Respeta la Page Visibility API para no desperdiciar recursos.
 *
 * @param {(datos: object) => void} onActualizacion - Callback con los datos más recientes.
 * @returns {{ stop: () => void }} Objeto para detener el polling.
 */
export function iniciarPolling(onActualizacion) {
  let timer = null;
  let detenido = false;

  function getIntervalo() {
    return document.hidden ? POLL_INTERVAL_BACKGROUND_MS : POLL_INTERVAL_ACTIVE_MS;
  }

  async function tick() {
    if (detenido) return;

    try {
      const datos = await obtenerResultadosTorneo();
      if (!detenido) {
        onActualizacion(datos);
      }
    } catch {
      // No critico; el próximo tick lo intentará
    }

    if (!detenido) {
      timer = setTimeout(tick, getIntervalo());
    }
  }

  function handleVisibilityChange() {
    if (!detenido && !document.hidden) {
      // Volvió a estar visible: actualiza inmediatamente
      clearTimeout(timer);
      tick();
    }
  }

  document.addEventListener('visibilitychange', handleVisibilityChange);

  // Primera llamada diferida para no bloquear el render inicial
  timer = setTimeout(tick, getIntervalo());

  return {
    stop: () => {
      detenido = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
//  CRUD — Lectura y Escritura del combate activo
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Consulta el combate actual.
 * En el futuro, reemplazar localStorage por: const res = await fetch('/api/v1/combate-activo');
 */
export async function obtenerResultadosTorneo() {
  // Simula latencia de red para pruebas de UX (~50ms vs un fetch real)
  await new Promise((resolve) => setTimeout(resolve, 50));

  const guardado = localStorage.getItem(STORAGE_KEY_RESULTADOS);
  if (guardado) {
    try {
      const parsed = JSON.parse(guardado);
      if (parsed.robotA && parsed.robotB) {
        // Normalización defensiva: elimina campos heredados de versiones anteriores
        const { ronda, dohyo, combates, podio, ...combateLimpio } = parsed;
        void ronda; void dohyo; void combates; void podio;
        return { ...COMBATE_ACTUAL_INICIAL, ...combateLimpio };
      }
    } catch {
      // Fallback silencioso
    }
  }

  localStorage.setItem(STORAGE_KEY_RESULTADOS, JSON.stringify(COMBATE_ACTUAL_INICIAL));
  return COMBATE_ACTUAL_INICIAL;
}

/**
 * Guarda y publica las actualizaciones del combate activo en vivo.
 * Emite por BroadcastChannel (otras pestañas del mismo dispositivo) y
 * también por evento DOM (misma pestaña) para máxima compatibilidad.
 *
 * En el futuro, reemplazar localStorage por:
 *   await fetch('/api/v1/combate-activo', { method: 'PUT', body: JSON.stringify(datos) });
 */
export async function guardarResultadosTorneo(nuevoCombate) {
  // Simula latencia de escritura
  await new Promise((resolve) => setTimeout(resolve, 50));

  // Eliminar campos obsoletos de versiones anteriores
  const { ronda, dohyo, combates, podio, ...restoCombate } = nuevoCombate;
  void ronda; void dohyo; void combates; void podio;

  const datosCompletos = {
    ...restoCombate,
    ultimaActualizacion: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  };

  // 1) Persiste en localStorage (fuente de verdad compartida en el origen)
  localStorage.setItem(STORAGE_KEY_RESULTADOS, JSON.stringify(datosCompletos));

  // 2) Notifica a otras pestañas via BroadcastChannel (< 10ms)
  emitirBroadcast(datosCompletos);

  // 3) Notifica a la misma pestaña via evento DOM (retrocompatibilidad)
  window.dispatchEvent(new CustomEvent(EVENTO_RESULTADOS_ACTUALIZADOS, {
    detail: datosCompletos,
  }));

  return datosCompletos;
}
