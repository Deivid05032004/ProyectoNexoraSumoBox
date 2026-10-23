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
  const [usuario, participante, eventos, instituciones] = await Promise.all([
    solicitud('/api/v1/auth/me', token),
    solicitud('/api/v1/participants/me', token),
    solicitud('/api/v1/events?limit=100', token),
    fetch(`${API_BASE}/api/v1/institutions?limit=100`).then(mensajeRespuesta),
  ])

  if (usuario.role !== 'PARTICIPANT') throw new Error('El formulario de inscripción es exclusivo para participantes.')
  return { participante, eventos, instituciones }
}

export async function cargarConfiguracionEvento(eventId) {
  const response = await fetch(`${API_BASE}/api/v1/events/${eventId}/registration-config`)
  return mensajeRespuesta(response)
}

export async function cargarCategoriasEvento(eventId) {
  const response = await fetch(`${API_BASE}/api/v1/events/${eventId}/categories`)
  return mensajeRespuesta(response)
}

export async function cargarMisOrdenes(token) {
  return solicitud('/api/v1/payments/my?limit=100', token)
}

async function obtenerOCrearRecurso(path, token, nombre, payload, coincide) {
  const existentes = await solicitud(`${path}?limit=100`, token)
  const existente = existentes.find((item) => (
    item.name.trim().toLocaleUpperCase() === nombre.trim().toLocaleUpperCase()
    && coincide(item)
  ))
  if (existente) return existente
  return solicitud(path, token, { method: 'POST', body: JSON.stringify(payload) })
}

export async function crearInscripcion({
  token,
  eventId,
  categoryId,
  participant,
  teamName,
  robotName,
  participants,
}) {
  const equipo = await obtenerOCrearRecurso(
    '/api/v1/teams',
    token,
    teamName,
    {
      name: teamName,
      institution_id: participant.institution_id,
      contact_phone: participant.mobile_phone || null,
    },
    (item) => item.institution_id === participant.institution_id,
  )
  const robot = await obtenerOCrearRecurso(
    '/api/v1/robots',
    token,
    robotName,
    { name: robotName, robot_description: null },
    () => true,
  )
  return solicitud('/api/v1/registrations', token, {
    method: 'POST',
    body: JSON.stringify({
      event_id: Number(eventId),
      category_id: Number(categoryId),
      team_id: equipo.id,
      robot_id: robot.id,
      participants: participants.map((item) => ({
        role: item.role,
        first_name: item.first_name.trim(),
        last_name: item.last_name.trim(),
        institution_id: Number(item.institution_id),
        mobile_phone: item.mobile_phone.trim(),
      })),
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

export async function descargarInstruccionesPago(registro, token) {
  const receiptUrl = registro.receipt_url
    || `/api/v1/registrations/${registro.registration_id || registro.id}/receipt`
  const response = await fetch(`${API_BASE}${receiptUrl}`, {
    headers: encabezadosAutorizados(token),
  })
  if (!response.ok) {
    await mensajeRespuesta(response)
    return
  }
  const archivo = URL.createObjectURL(await response.blob())
  const enlace = document.createElement('a')
  enlace.href = archivo
  enlace.download = `inscripcion-${registro.id}-pago.pdf`
  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()
  window.setTimeout(() => URL.revokeObjectURL(archivo), 1000)
}
