const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

async function mensajeRespuesta(response) {
  const body = await response.json().catch(() => ({}))
  if (response.ok) return body
  const detail = Array.isArray(body.detail) ? body.detail.map((item) => item.msg).join(' ') : body.detail
  throw new Error(detail || `No se pudo completar la solicitud (${response.status}).`)
}

function encabezadosAutorizados(token, json = false) {
  return {
    Authorization: `Bearer ${token}`,
    ...(json ? { 'Content-Type': 'application/json' } : {}),
  }
}

async function solicitud(path, token, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...encabezadosAutorizados(token, Boolean(options.body)), ...options.headers },
  })
  return mensajeRespuesta(response)
}

export async function cargarDatosInscripcion(token) {
  const [usuario, participante, eventos, categorias, instituciones] = await Promise.all([
    solicitud('/api/v1/auth/me', token),
    solicitud('/api/v1/participants/me', token),
    solicitud('/api/v1/events?limit=100', token),
    fetch(`${API_BASE}/api/v1/categories?limit=100`).then(mensajeRespuesta),
    fetch(`${API_BASE}/api/v1/institutions?limit=100`).then(mensajeRespuesta),
  ])

  if (usuario.role !== 'PARTICIPANT') throw new Error('El formulario de inscripción es exclusivo para participantes.')
  const categoria = categorias.find((item) => item.name === 'MINI SUMO RC AMATEUR')
  if (!categoria) throw new Error('La categoría MINI SUMO RC AMATEUR no está disponible.')
  return { participante, eventos, categoria, instituciones }
}

export async function cargarTarifa(token, eventId, categoryId) {
  const tarifas = await fetch(`${API_BASE}/api/v1/tariffs?event_id=${eventId}&category_id=${categoryId}&limit=10`, {
    headers: encabezadosAutorizados(token),
  }).then(mensajeRespuesta)
  return tarifas[0] || null
}

async function obtenerOCrearRecurso(path, token, nombre, payload) {
  const existentes = await solicitud(`${path}?limit=100`, token)
  const existente = existentes.find((item) => item.name.trim().toLocaleUpperCase() === nombre.trim().toLocaleUpperCase())
  if (existente) return existente
  return solicitud(path, token, { method: 'POST', body: JSON.stringify(payload) })
}

export async function crearInscripcion({ token, eventId, categoryId, participant, teamName, robotName }) {
  const equipo = await obtenerOCrearRecurso('/api/v1/teams', token, teamName, {
    name: teamName,
    institution_id: participant.institution_id,
    contact_phone: participant.mobile_phone || null,
  })
  const robot = await obtenerOCrearRecurso('/api/v1/robots', token, robotName, {
    name: robotName,
    robot_description: null,
  })
  return solicitud('/api/v1/registrations', token, {
    method: 'POST',
    body: JSON.stringify({
      event_id: Number(eventId),
      category_id: categoryId,
      team_id: equipo.id,
      robot_id: robot.id,
      participants: [{ participant_id: participant.id, role: 'PARTICIPANT' }],
      notes: null,
    }),
  })
}

export async function subirComprobante(paymentId, archivo, token, referencia = '') {
  const formData = new FormData()
  formData.append('file', archivo)
  if (referencia.trim()) formData.append('payment_reference', referencia.trim())
  const response = await fetch(`${API_BASE}/api/v1/payments/${paymentId}/receipt`, {
    method: 'POST',
    headers: encabezadosAutorizados(token),
    body: formData,
  })
  return mensajeRespuesta(response)
}
