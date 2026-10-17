const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1'

/** Envía el formulario como multipart/form-data al POST /api/v1/inscripciones. */
export async function crearInscripcion(datos, comprobante) {
  const formData = new FormData()
  formData.append('datos', JSON.stringify(datos))
  formData.append('comprobante', comprobante)

  let respuesta
  try {
    respuesta = await fetch(`${API_URL}/inscripciones`, {
      method: 'POST',
      body: formData,
    })
  } catch {
    throw new Error('No se pudo conectar con el servidor. Verifica tu conexión e inténtalo nuevamente.')
  }

  const contenido = await respuesta.json().catch(() => ({}))

  if (!respuesta.ok) {
    const detalle = Array.isArray(contenido.detail)
      ? contenido.detail.map((error) => error.msg).join(' ')
      : contenido.detail
    throw new Error(detalle || 'No fue posible enviar la inscripción. Inténtalo nuevamente.')
  }

  return contenido
}
