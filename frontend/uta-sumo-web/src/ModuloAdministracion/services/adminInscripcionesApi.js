/**
 * Servicio simulado para la gestión administrativa de inscripciones.
 * En producción, simplemente se reemplazan estas llamadas por peticiones fetch a la API real.
 */

export const MOCK_INSCRIPCIONES = [
  {
    id: 1,
    codigo: 'SUMO-0005',
    fecha: '12 oct',
    robot: 'Rayo',
    institucion: 'Colegio Nacional Bolívar',
    categoria: 'Mini Sumo RC Amateur',
    integrantes: [
      { nombre: 'Iván Toapanta', celular: '0981230001', esCoach: false },
      { nombre: 'Nelly Guamán', celular: '0981230002', esCoach: false },
      { nombre: 'Jorge Silva', celular: '0993334455', esCoach: true },
    ],
    tarifa: 15,
    estado: 'Aprobado',
    revisor: 'revisor1',
  },
  {
    id: 2,
    codigo: 'SUMO-0004',
    fecha: '9 oct',
    robot: 'Katana II',
    institucion: 'UTA · FISEI',
    categoria: 'Mini Sumo RC Amateur',
    integrantes: [
      { nombre: 'Diego Vera', celular: '0984445566', esCoach: false },
      { nombre: 'María Cuji', celular: '0985556677', esCoach: false },
      { nombre: 'Pablo Rocha', celular: '0986667788', esCoach: true },
    ],
    tarifa: 15,
    estado: 'Pendiente',
    revisor: null,
  },
  {
    id: 3,
    codigo: 'SUMO-0003',
    fecha: '7 oct',
    robot: 'Titán',
    institucion: 'U.E. Juan Montalvo',
    categoria: 'Mini Sumo RC Amateur',
    integrantes: [
      { nombre: 'Sofía León', celular: '0997778899', esCoach: false },
      { nombre: 'Mateo Freire', celular: '0998889900', esCoach: false },
      { nombre: 'Carla Núñez', celular: '0999990011', esCoach: true },
    ],
    tarifa: 15,
    estado: 'Pendiente',
    revisor: null,
  },
  {
    id: 4,
    codigo: 'SUMO-0002',
    fecha: '3 oct',
    robot: 'Katana',
    institucion: 'UTA · FISEI',
    categoria: 'Mini Sumo RC Amateur',
    integrantes: [
      { nombre: 'Diego Vera', celular: '0984445566', esCoach: false },
      { nombre: 'María Cuji', celular: '0985556677', esCoach: false },
      { nombre: 'Pablo Rocha', celular: '0986667788', esCoach: true },
    ],
    tarifa: 10,
    estado: 'Aprobado',
    revisor: 'revisor1',
  },
  {
    id: 5,
    codigo: 'SUMO-0001',
    fecha: '2 oct',
    robot: 'Tigre RC',
    institucion: 'Colegio Nacional Bolívar',
    categoria: 'Mini Sumo RC Amateur',
    integrantes: [
      { nombre: 'Luis Mena', celular: '0991112233', esCoach: false },
      { nombre: 'Ana Paredes', celular: '0992223344', esCoach: false },
      { nombre: 'Jorge Silva', celular: '0993334455', esCoach: true },
    ],
    tarifa: 10,
    estado: 'Aprobado',
    revisor: 'revisor1',
  },
];

const STORAGE_KEY = 'uta.admin.inscripciones';

/**
 * Obtiene la lista de inscripciones (simula fetch asíncrono).
 */
export async function obtenerInscripciones() {
  // Simulación de latencia de red:
  await new Promise((resolve) => setTimeout(resolve, 250));

  const local = localStorage.getItem(STORAGE_KEY);
  if (local) {
    try {
      return JSON.parse(local);
    } catch {
      // fallback a mock
    }
  }

  // Guardar copia inicial en localStorage para permitir cambios persistentes durante la prueba
  localStorage.setItem(STORAGE_KEY, JSON.stringify(MOCK_INSCRIPCIONES));
  return MOCK_INSCRIPCIONES;
}

/**
 * Actualiza el estado de una inscripción (Pendiente / Aprobado).
 */
export async function actualizarEstadoInscripcion(id, nuevoEstado, revisor) {
  await new Promise((resolve) => setTimeout(resolve, 150));

  const local = localStorage.getItem(STORAGE_KEY);
  let lista = local ? JSON.parse(local) : [...MOCK_INSCRIPCIONES];

  lista = lista.map((item) => {
    if (item.id === id) {
      return {
        ...item,
        estado: nuevoEstado,
        revisor: nuevoEstado === 'Aprobado' ? (revisor || 'revisor1') : null,
      };
    }
    return item;
  });

  localStorage.setItem(STORAGE_KEY, JSON.stringify(lista));
  return lista;
}

/**
 * Exporta el listado actual en formato CSV compatible con Excel.
 */
export function exportarInscripcionesCSV(inscripciones) {
  if (!inscripciones || inscripciones.length === 0) return;

  const encabezados = ['Código', 'Fecha', 'Robot', 'Institución', 'Categoría', 'Tarifa', 'Estado', 'Revisor', 'Integrantes'];
  
  const filas = inscripciones.map((ins) => {
    const integrantesStr = ins.integrantes
      .map((m) => `${m.nombre} (${m.celular}${m.esCoach ? ' - Coach' : ''})`)
      .join('; ');

    return [
      `"${ins.codigo}"`,
      `"${ins.fecha}"`,
      `"${ins.robot}"`,
      `"${ins.institucion}"`,
      `"${ins.categoria}"`,
      `"$${ins.tarifa}"`,
      `"${ins.estado}"`,
      `"${ins.revisor || 'Sin revisar'}"`,
      `"${integrantesStr}"`,
    ].join(',');
  });

  const contenidoCSV = '\uFEFF' + [encabezados.join(','), ...filas].join('\r\n');
  const blob = new Blob([contenidoCSV], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const enlace = document.createElement('a');
  enlace.setAttribute('href', url);
  enlace.setAttribute('download', `inscripciones_uta_sumo_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(enlace);
  enlace.click();
  document.body.removeChild(enlace);
  URL.revokeObjectURL(url);
}

