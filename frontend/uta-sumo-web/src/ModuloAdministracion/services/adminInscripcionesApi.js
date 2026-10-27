import { apiBlob, apiRequest } from './adminApi';

const statusLabels = {
  PENDING: 'Pendiente', APPROVED: 'Aprobado', OBSERVED: 'Observado',
  REJECTED: 'Rechazado', PAYMENT_PENDING: 'Pago pendiente',
  PAYMENT_REVIEW: 'Pago en revisión', CANCELLED: 'Cancelado',
};

const paymentStatusLabels = {
  PENDING: 'Pendiente de comprobante', IN_REVIEW: 'En revisión',
  PAID: 'Pagado', REJECTED: 'Rechazado',
};

function mapRegistration(row, detail = {}) {
  const people = detail.participants || [];
  return {
    id: row.id,
    codigo: row.code,
    fecha: row.registered_at ? new Date(row.registered_at).toLocaleDateString() : '',
    equipo: row.team_name || detail.team_name || '—',
    robot: row.robot_name || detail.robot_name || '—',
    institucion: people[0]?.institution_name || '—',
    categoria: row.category_name || detail.category_name || '—',
    categoriaId: row.category_id || detail.category_id,
    integrantes: people.map((person) => ({
      nombre: `${person.first_name} ${person.last_name}`.trim(),
      celular: person.mobile_phone || '',
      esCoach: person.role === 'COACH',
    })),
    tarifa: row.amount ?? detail.amount ?? 0,
    estado: row.registration_status || detail.status,
    estadoLabel: statusLabels[row.registration_status || detail.status] || row.registration_status,
    paymentId: row.payment_id,
    paymentStatus: row.payment_status,
    paymentStatusLabel: paymentStatusLabels[row.payment_status] || 'Sin pago',
    hasReceipt: Boolean(row.has_receipt),
    receiptUploadedAt: row.receipt_uploaded_at,
    revisor: row.payment_verified_by ? String(row.payment_verified_by) : null,
    raw: row,
  };
}

export async function obtenerInscripciones({ eventId, categoria, estado, page = 1 } = {}) {
  const params = new URLSearchParams({ page: String(page), limit: '5' });
  if (eventId) params.set('event_id', String(eventId));
  if (categoria) params.set('category_id', String(categoria));
  const statusCodes = {
    'Pago pendiente': 'PAYMENT_PENDING', 'Pago en revisión': 'PAYMENT_REVIEW',
    Pendiente: 'PENDING', Aprobado: 'APPROVED', Observado: 'OBSERVED', Rechazado: 'REJECTED',
  };
  if (estado && statusCodes[estado]) params.set('status', statusCodes[estado]);
  const result = await apiRequest(`/api/v1/admin/registrations?${params}`);
  const mapped = await Promise.all((result.items || []).map(async (row) => {
    try {
      const detail = await apiRequest(`/api/v1/registrations/${row.id}`);
      return mapRegistration(row, detail);
    } catch {
      return mapRegistration(row);
    }
  }));
  return { ...result, items: mapped };
}

export async function obtenerTodasLasInscripciones({ eventId, categoria, estado } = {}) {
  const firstPage = await obtenerInscripciones({ eventId, categoria, estado, page: 1 });
  const rows = [...firstPage.items];
  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await obtenerInscripciones({ eventId, categoria, estado, page });
    rows.push(...result.items);
  }
  return rows;
}

export async function actualizarEstadoInscripcion(id, nuevoEstado) {
  const reviewStatus = {
    APPROVED: 'APPROVED', PENDING: 'PENDING', OBSERVED: 'OBSERVED', REJECTED: 'REJECTED',
    Aprobado: 'APPROVED', Pendiente: 'PENDING', Observado: 'OBSERVED', Rechazado: 'REJECTED',
  }[nuevoEstado];
  if (!reviewStatus) throw new Error('Estado de inscripción no soportado.');
  await apiRequest(`/api/v1/registrations/${id}/review`, {
    method: 'POST', body: JSON.stringify({ status: reviewStatus }),
  });
}

export async function actualizarEstadoPago(paymentId, status, comments = '') {
  if (!paymentId) throw new Error('La inscripción no tiene un pago asociado.');
  if (!['PAID', 'REJECTED'].includes(status)) throw new Error('Estado de pago no soportado.');
  return apiRequest(`/api/v1/payments/${paymentId}/review`, {
    method: 'POST',
    body: JSON.stringify({ status, comments }),
  });
}

export async function obtenerComprobante(paymentId) {
  if (!paymentId) throw new Error('La inscripción no tiene un pago asociado.');
  return apiBlob(`/api/v1/payments/${paymentId}/receipt/preview`);
}

export function exportarInscripcionesCSV(inscripciones) {
  if (!inscripciones?.length) return;
  const headers = ['Código', 'Robot', 'Institución', 'Categoría', 'Tarifa', 'Estado', 'Integrantes'];
  const rows = inscripciones.map((item) => [item.codigo, item.robot, item.institucion, item.categoria,
    item.tarifa, item.estadoLabel, item.integrantes.map((p) => `${p.nombre} (${p.celular}${p.esCoach ? ', coach' : ''})`).join('; ')]
    .map((value) => `"${String(value ?? '').replaceAll('"', '""')}"`).join(','));
  const blob = new Blob(['\uFEFF' + [headers.join(','), ...rows].join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `inscripciones_${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
