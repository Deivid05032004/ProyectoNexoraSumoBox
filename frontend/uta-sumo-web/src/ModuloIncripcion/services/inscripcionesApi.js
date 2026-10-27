const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export function urlApi(path) {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

async function mensajeRespuesta(response) {
  const body = await response.json().catch(() => ({}))
  if (response.ok) return body
  const detail = Array.isArray(body.detail)
    ? body.detail.map((item) => item.msg).join(' ')
    : body.detail
  const error = new Error(
    (detail && typeof detail === 'object' ? detail.message : detail)
      || `No se pudo completar la solicitud (${response.status}).`,
  )
  if (detail && typeof detail === 'object') {
    error.code = detail.code
    error.field = detail.field
  }
  throw error
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

export async function cargarCategoriasEvento(eventId, categoryId = null) {
  const query = categoryId ? `?category_id=${encodeURIComponent(categoryId)}&limit=5` : '?page=1&limit=5'
  const response = await fetch(`${API_BASE}/api/v1/events/${eventId}/categories${query}`)
  return mensajeRespuesta(response)
}

export async function cargarFormularioEvento(eventId) {
  const response = await fetch(`${API_BASE}/api/v1/events/${eventId}/form`)
  return mensajeRespuesta(response)
}

export async function cargarReglamentosEvento(eventId, categoryId = null) {
  const params = new URLSearchParams()
  if (categoryId) params.set('category_id', categoryId)
  const query = params.size ? `?${params.toString()}` : ''
  const response = await fetch(urlApi(`/api/v1/events/${eventId}/regulations${query}`))
  return mensajeRespuesta(response)
}

export async function cargarMisOrdenes(token) {
  return solicitud('/api/v1/payments/my?limit=100', token)
}

export async function crearInscripcion({
  token,
  eventId,
  categoryId,
  participant,
  teamName,
  robotName,
  participants,
  customAnswers = {},
}) {
  const resources = await solicitud('/api/v1/registration-resources', token, {
    method: 'POST',
    body: JSON.stringify({
      team_name: teamName,
      robot_name: robotName,
      institution_id: participant.institution_id,
      contact_phone: participant.mobile_phone || null,
      robot_description: null,
    }),
  })
  return solicitud('/api/v1/registrations', token, {
    method: 'POST',
    body: JSON.stringify({
      event_id: Number(eventId),
      category_id: Number(categoryId),
      team_id: resources.team.id,
      robot_id: resources.robot.id,
      participants: participants.map((item) => ({
        role: item.role,
        first_name: item.first_name.trim(),
        last_name: item.last_name.trim(),
        institution_id: Number(item.institution_id),
        mobile_phone: item.mobile_phone.trim(),
      })),
      custom_answers: customAnswers,
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
