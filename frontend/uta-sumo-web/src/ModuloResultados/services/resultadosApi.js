/**
 * Servicio de Resultados con sincronización del backend y canales locales.
 *
 * Capas de sincronización implementadas:
 *  1. BroadcastChannel API — instantáneo entre pestañas del mismo origen (mismo dispositivo).
 *     El admin guarda → la pantalla gigante en otra pestaña recibe en < 10ms.
 *  2. Polling inteligente — refresca cada POLL_INTERVAL_MS cuando la pestaña está visible,
 *     o cada POLL_BACKGROUND_MS cuando está en background.
 *     Garantiza sincronización entre dispositivos distintos (admin en laptop, pantalla en TV).
 *  3. Page Visibility API — pausa el polling agresivo cuando la pestaña no está activa.
 *
 * El snapshot público del backend es la fuente principal. localStorage,
 * BroadcastChannel y los eventos DOM conservan compatibilidad local/offline.
 */

const STORAGE_KEY_RESULTADOS = 'uta.torneo.resultados';
const STORAGE_KEY_CRONOMETRO = 'uta.torneo.cronometro';
const BROADCAST_CHANNEL_NAME = 'uta-resultados-channel';
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const API_WS_BASE = API_BASE
  ? API_BASE.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

/** Nombre del evento DOM interno para notificar dentro de la misma pestaña. */
export const EVENTO_RESULTADOS_ACTUALIZADOS = 'uta-resultados-updated';
export const EVENTO_CRONOMETRO_ACTUALIZADO = 'uta-cronometro-updated';
export const CRONOMETRO_INICIAL = { enabled: false, seconds: 180 };

/** Escucha el snapshot en vivo publicado por FastAPI; polling sigue como respaldo. */
export function suscribirWebSocketCombate(onActualizacion) {
  let detenido = false;
  let socket;
  let retryTimer;
  let intentos = 0;

  function conectar() {
    if (detenido || typeof WebSocket === 'undefined') return;
    try {
      socket = new WebSocket(`${API_WS_BASE}/ws/combate-actual`);
      socket.onopen = () => { intentos = 0; };
      socket.onmessage = (event) => {
        try {
          const snapshot = JSON.parse(event.data);
          if (snapshot?.robotA && snapshot?.robotB) {
            onActualizacion({ ...COMBATE_ACTUAL_INICIAL, ...snapshot });
          }
        } catch { /* El polling recupera snapshots inválidos */ }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (detenido) return;
        intentos += 1;
        retryTimer = setTimeout(conectar, Math.min(15000, 1000 * (2 ** Math.min(intentos - 1, 4))));
      };
    } catch {
      if (!detenido) retryTimer = setTimeout(conectar, 5000);
    }
  }

  conectar();
  return {
    stop: () => {
      detenido = true;
      clearTimeout(retryTimer);
      socket?.close();
    },
  };
}

/** Suscribe la transmisión completa del torneo (todos los Dohyos y grupos). */
export function suscribirWebSocketTorneo(eventId, categoryId, onActualizacion) {
  if (!eventId || !categoryId || typeof WebSocket === 'undefined') return { stop: () => {} };
  let detenido = false;
  let socket;
  let retryTimer;
  let intentos = 0;
  const url = `${API_WS_BASE}/api/v1/events/${encodeURIComponent(eventId)}/live?category_id=${encodeURIComponent(categoryId)}`;

  function conectar() {
    if (detenido) return;
    try {
      socket = new WebSocket(url);
      socket.onopen = () => { intentos = 0; };
      socket.onmessage = (event) => {
        try {
          const snapshot = JSON.parse(event.data);
          if (snapshot?.tournament) onActualizacion(snapshot);
        } catch { /* El polling continúa como respaldo. */ }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (detenido) return;
        intentos += 1;
        retryTimer = setTimeout(conectar, Math.min(15000, 1000 * (2 ** Math.min(intentos - 1, 4))));
      };
    } catch {
      if (!detenido) retryTimer = setTimeout(conectar, 5000);
    }
  }

  conectar();
  return { stop: () => { detenido = true; clearTimeout(retryTimer); socket?.close(); } };
}

export function obtenerConfiguracionCronometro() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY_CRONOMETRO) || 'null');
    if (stored && typeof stored.enabled === 'boolean' && Number.isFinite(Number(stored.seconds))) {
      return { enabled: stored.enabled, seconds: Math.max(1, Math.floor(Number(stored.seconds))) };
    }
  } catch { /* Usa valores iniciales */ }
  return CRONOMETRO_INICIAL;
}

export function guardarConfiguracionCronometro(config) {
  const value = { enabled: Boolean(config.enabled), seconds: Math.max(1, Math.floor(Number(config.seconds) || 180)) };
  localStorage.setItem(STORAGE_KEY_CRONOMETRO, JSON.stringify(value));
  window.dispatchEvent(new CustomEvent(EVENTO_CRONOMETRO_ACTUALIZADO, { detail: value }));
  return value;
}

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
 * Consulta el snapshot público del combate; conserva localStorage como fallback
 * para que la pantalla siga funcionando si la API no está disponible.
 */
export async function obtenerResultadosTorneo() {
  try {
    const response = await fetch(`${API_BASE}/api/v1/competition/combate-actual`);
    if (response.ok) {
      const snapshot = await response.json();
      if (snapshot?.robotA && snapshot?.robotB) {
        return {
          ...COMBATE_ACTUAL_INICIAL,
          ...snapshot,
          ultimaActualizacion: snapshot.ultimaActualizacion || '--:--',
        };
      }
    }
  } catch {
    // Use the locally stored scoreboard as an offline fallback.
  }

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

/** Lee la clasificación persistida por el backend para el evento del combate. */
export async function obtenerTablaPosiciones(eventId) {
  if (!eventId) return [];
  const response = await fetch(`${API_BASE}/api/v1/events/${eventId}/leaderboard`);
  if (!response.ok) throw new Error(`No se pudo cargar la tabla de posiciones (${response.status}).`);
  const data = await response.json();
  return data.items || [];
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
