const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const MENSAJES_HTTP = {
  400: 'La solicitud tiene datos incorrectos. Revisa la información e inténtalo de nuevo.',
  401: 'Tu sesión venció o no es válida. Inicia sesión nuevamente.',
  403: 'Tu cuenta no tiene permisos para realizar esta acción.',
  404: 'No se encontró el recurso solicitado.',
  405: 'El backend que está ejecutándose todavía no tiene disponible esta operación. Reinícialo y vuelve a intentarlo.',
  409: 'La acción entra en conflicto con el estado actual del evento o del registro.',
  413: 'El archivo supera el tamaño máximo permitido.',
  422: 'Revisa los campos: hay datos obligatorios incompletos o valores no válidos.',
  429: 'Se realizaron demasiadas solicitudes. Espera un momento e inténtalo nuevamente.',
  500: 'Ocurrió un error interno. Inténtalo nuevamente y, si continúa, revisa los registros del backend.',
  503: 'El servicio o la base de datos no están disponibles en este momento.',
};

export function mensajeErrorApi(status, detail) {
  const isKnownEnglishError = (message) => /^(Method Not Allowed|Not Found|Unauthorized|Forbidden|Conflict|Internal Server Error|Field required|Input should|String should|Value error|Request validation error)/i.test(message);
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => item.msg).filter(Boolean);
    if (messages.length && messages.every((message) => !isKnownEnglishError(message))) return messages.join(' ');
  } else if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message;
  } else if (typeof detail === 'string' && !isKnownEnglishError(detail)) {
    return detail;
  }
  return MENSAJES_HTTP[status] || `No se pudo completar la solicitud (error ${status}).`;
}

async function leerError(response) {
  let detail;
  try { detail = (await response.json()).detail; } catch { /* respuesta sin JSON */ }
  return mensajeErrorApi(response.status, detail);
}

async function solicitarApi(url, options) {
  try {
    return await fetch(url, options);
  } catch {
    throw new Error('No se pudo conectar con el servidor. Comprueba que el backend esté encendido e inténtalo nuevamente.');
  }
}

export function adminWebSocketUrl(path) {
  const socketBase = API_BASE.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:');
  return `${socketBase}${path.startsWith('/') ? path : `/${path}`}`;
}

export async function apiRequest(path, options = {}) {
  const token = sessionStorage.getItem('uta.access_token');
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await solicitarApi(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    throw new Error(await leerError(response));
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function apiRequestPage(path, options = {}) {
  const token = sessionStorage.getItem('uta.access_token');
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await solicitarApi(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    throw new Error(await leerError(response));
  }
  const data = response.status === 204 ? null : await response.json();
  return {
    data,
    page: Number(response.headers.get('x-page') || data?.page || 1),
    pageSize: Number(response.headers.get('x-page-size') || data?.page_size || 5),
    total: Number(response.headers.get('x-total-count') || data?.total || 0),
    totalPages: Number(response.headers.get('x-total-pages') || data?.total_pages || 0),
  };
}

export async function apiBlob(path) {
  const token = sessionStorage.getItem('uta.access_token');
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await solicitarApi(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
    throw new Error(await leerError(response));
  }
  return response.blob();
}

export function getAdminUser() {
  try { return JSON.parse(sessionStorage.getItem('uta.user') || 'null'); }
  catch { return null; }
}

export function setAdminSession(auth) {
  sessionStorage.setItem('uta.access_token', auth.access_token);
  sessionStorage.setItem('uta.user', JSON.stringify(auth.user));
  sessionStorage.setItem('uta.revisor', auth.user.email);
  window.dispatchEvent(new Event('uta-session-changed'));
}

export function clearAdminSession() {
  ['uta.access_token', 'uta.user', 'uta.revisor'].forEach((key) => sessionStorage.removeItem(key));
  window.dispatchEvent(new Event('uta-session-changed'));
}
