const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export async function apiRequest(path, options = {}) {
  const token = sessionStorage.getItem('uta.access_token');
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Error HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = Array.isArray(body.detail)
        ? body.detail.map((item) => `${item.loc?.slice(-1)[0] || 'Solicitud'}: ${item.msg}`).join(' ')
        : body.detail || message;
    } catch { /* response without JSON body */ }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function apiBlob(path) {
  const token = sessionStorage.getItem('uta.access_token');
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
    let message = `Error HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = Array.isArray(body.detail)
        ? body.detail.map((item) => item.msg).join(' ')
        : body.detail || message;
    } catch { /* respuesta sin cuerpo JSON */ }
    throw new Error(message);
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
