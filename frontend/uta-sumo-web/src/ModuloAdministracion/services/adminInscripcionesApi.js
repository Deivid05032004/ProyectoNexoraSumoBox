import { apiRequest } from './adminApi';

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
    revisor: row.payment_verified_by ? String(row.payment_verified_by) : null,
    raw: row,
  };
}

export async function obtenerInscripciones({ categoria, estado } = {}) {
  const params = new URLSearchParams({ page: '1', limit: '100' });
  // The API accepts `status`, but has no institution or category filter.
  // Category remains a client-side filter; status is mapped to backend codes.
  const statusCodes = {
    'Pago pendiente': 'PAYMENT_PENDING', 'Pago en revisión': 'PAYMENT_REVIEW',
    Pendiente: 'PENDING', Aprobado: 'APPROVED', Observado: 'OBSERVED', Rechazado: 'REJECTED',
  };
  if (estado && statusCodes[estado]) params.set('status', statusCodes[estado]);
  let result = await apiRequest(`/api/v1/admin/registrations?${params}`);
  const rows = [...(result.items || [])];
  for (let page = 2; page <= (result.total_pages || 1); page += 1) {
    params.set('page', String(page));
    result = await apiRequest(`/api/v1/admin/registrations?${params}`);
    rows.push(...(result.items || []));
  }
  const mapped = await Promise.all(rows.map(async (row) => {
    try {
      const detail = await apiRequest(`/api/v1/registrations/${row.id}`);
      return mapRegistration(row, detail);
    } catch {
      return mapRegistration(row);
    }
  }));
  return mapped.filter((item) => !categoria || item.categoriaId === Number(categoria));
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

export async function actualizarEstadoPago(paymentId, status) {
  if (!paymentId) throw new Error('La inscripción no tiene un pago asociado.');
  if (!['PAID', 'REJECTED'].includes(status)) throw new Error('Estado de pago no soportado.');
  return apiRequest(`/api/v1/payments/${paymentId}/review`, {
    method: 'POST',
    body: JSON.stringify({
      status,
      comments: status === 'REJECTED'
        ? 'Comprobante rechazado desde el panel administrativo.'
        : 'Pago verificado desde el panel administrativo.',
    }),
  });
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
