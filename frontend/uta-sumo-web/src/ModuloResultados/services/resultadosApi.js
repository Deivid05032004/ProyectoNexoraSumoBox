/**
 * Servicio para la gestión y consulta del Combate Actual en Tiempo Real.
 * Alimenta la pantalla gigante de /resultados y el panel de jueces de /admin/dashboard.
 */

const STORAGE_KEY_RESULTADOS = 'uta.torneo.resultados';
export const EVENTO_RESULTADOS_ACTUALIZADOS = 'uta-resultados-updated';

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
  estado: 'En combate', // 'En combate' | 'Finalizado' | 'Pausa técnica'
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
  ganador: 'No definido', // 'No definido' | 'Katana II' | 'Tornado' | 'Empate'
  detalles: '',
  tiempoSegundos: 180, // 3:00 estándar de sumo
  cronometroActivo: true,
  ultimaActualizacion: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
};

/**
 * Consulta el combate actual en tiempo real.
 */
export async function obtenerResultadosTorneo() {
  await new Promise((resolve) => setTimeout(resolve, 80));

  const guardado = localStorage.getItem(STORAGE_KEY_RESULTADOS);
  if (guardado) {
    try {
      const parsed = JSON.parse(guardado);
      if (parsed.robotA && parsed.robotB) {
        return {
          ...COMBATE_ACTUAL_INICIAL,
          ...parsed,
          ronda: undefined,
          dohyo: undefined,
        };
      }
    } catch {
      // Si falla el parseo, se usa el valor inicial
    }
  }

  localStorage.setItem(STORAGE_KEY_RESULTADOS, JSON.stringify(COMBATE_ACTUAL_INICIAL));
  return COMBATE_ACTUAL_INICIAL;
}

/**
 * Guarda y publica las actualizaciones del combate actual en vivo.
 */
export async function guardarResultadosTorneo(nuevoCombate) {
  await new Promise((resolve) => setTimeout(resolve, 80));

  const { ronda, dohyo, ...restoCombate } = nuevoCombate;
  void ronda;
  void dohyo;

  const datosCompletos = {
    ...restoCombate,
    ultimaActualizacion: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  };

  localStorage.setItem(STORAGE_KEY_RESULTADOS, JSON.stringify(datosCompletos));
  window.dispatchEvent(new Event(EVENTO_RESULTADOS_ACTUALIZADOS));
  return datosCompletos;
}
