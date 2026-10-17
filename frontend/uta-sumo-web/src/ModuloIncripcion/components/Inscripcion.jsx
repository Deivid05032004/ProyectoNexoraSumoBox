import { useState } from 'react'
import { crearInscripcion } from '../services/inscripcionesApi'
import Confirmacion from './Confirmacion'

const CATEGORIA = 'MINI SUMO RC AMATEUR'
const FECHA_CAMBIO_TARIFA = new Date('2026-10-06T00:00:00')
const TIPOS_COMPROBANTE = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
const TAMANIO_MAXIMO_ARCHIVO = 5 * 1024 * 1024
const crearIntegrantes = () => [
  { rol: 'PARTICIPANT', nombres: '', apellidos: '', institucion: '', celular: '' },
  { rol: 'PARTICIPANT', nombres: '', apellidos: '', institucion: '', celular: '' },
  { rol: 'COACH', nombres: '', apellidos: '', institucion: '', celular: '' },
]

function obtenerTarifa() { return new Date() >= FECHA_CAMBIO_TARIFA ? 15 : 10 }
function errorArchivo(archivo) {
  if (!archivo) return 'Adjunta el comprobante de transferencia.'
  if (!TIPOS_COMPROBANTE.includes(archivo.type)) return 'Adjunta una imagen JPG, PNG, WEBP o un archivo PDF.'
  if (archivo.size > TAMANIO_MAXIMO_ARCHIVO) return 'El comprobante no puede superar los 5 MB.'
  return ''
}

export default function Inscripcion() {
  const [equipo, setEquipo] = useState('')
  const [robot, setRobot] = useState('')
  const [integrantes, setIntegrantes] = useState(crearIntegrantes)
  const [comprobante, setComprobante] = useState(null)
  const [errores, setErrores] = useState({})
  const [enviando, setEnviando] = useState(false)
  const [registroExitoso, setRegistroExitoso] = useState(null)
  const tarifa = obtenerTarifa()

  const limpiarError = (campo) => setErrores((actuales) => ({ ...actuales, [campo]: '' }))
  const actualizarIntegrante = (indice, campo, valor) => setIntegrantes((actuales) =>
    actuales.map((integrante, posicion) => posicion === indice ? { ...integrante, [campo]: valor } : integrante)
  )

  function validarFormulario() {
    const nuevosErrores = {}
    if (!equipo.trim()) nuevosErrores.equipo = 'Este campo es obligatorio.'
    if (!robot.trim()) nuevosErrores.robot = 'Este campo es obligatorio.'
    integrantes.forEach((integrante, indice) => {
      ;['nombres', 'apellidos', 'institucion', 'celular'].forEach((campo) => {
        const clave = `integrante-${indice}-${campo}`
        const valor = integrante[campo].trim()
        if (!valor) nuevosErrores[clave] = 'Este campo es obligatorio.'
        else if (campo === 'celular' && !/^\d{10}$/.test(valor)) nuevosErrores[clave] = 'Ingresa un celular válido de 10 dígitos.'
      })
    })
    const errorComprobante = errorArchivo(comprobante)
    if (errorComprobante) nuevosErrores.comprobante = errorComprobante
    return nuevosErrores
  }

  async function manejarEnvio(evento) {
    evento.preventDefault()
    const nuevosErrores = validarFormulario()
    setErrores(nuevosErrores)
    if (Object.keys(nuevosErrores).length) return
    setEnviando(true)
    try {
      const respuesta = await crearInscripcion({
        nombre_equipo: equipo.trim(), nombre_robot: robot.trim(), categoria: CATEGORIA, tarifa,
        integrantes: integrantes.map(({ rol, nombres, apellidos, institucion, celular }) => ({ rol, nombres: nombres.trim(), apellidos: apellidos.trim(), institucion: institucion.trim(), celular: celular.trim() })),
      }, comprobante)
      setRegistroExitoso({ ...respuesta, equipo: equipo.trim(), robot: robot.trim(), tarifa })
    } catch (error) {
      setErrores({ servidor: error.message })
    } finally { setEnviando(false) }
  }

  function reiniciarFormulario() {
    setEquipo(''); setRobot(''); setIntegrantes(crearIntegrantes()); setComprobante(null); setErrores({}); setRegistroExitoso(null)
  }

  if (registroExitoso) return <Confirmacion codigo={registroExitoso.codigo_inscripcion} equipo={registroExitoso.equipo} robot={registroExitoso.robot} tarifa={registroExitoso.tarifa} onNuevaInscripcion={reiniciarFormulario} />

  return <section className="registration-section" id="inscripcion">
    <div className="section-heading">
      <span className="eyebrow">REGISTRO OFICIAL</span>
      <h1>UTA SUMO ROBOTICS CUP</h1>
      <p>Registra un robot por envío. El mismo equipo puede registrar más de un robot.</p>
    </div>
    <form className="registration-card" onSubmit={manejarEnvio} noValidate>
      <div className="registration-summary">
        <div><span>Categoría</span><strong>{CATEGORIA}</strong></div>
        <div><span>Valor de inscripción</span><strong>${tarifa}.00</strong><small>{tarifa === 10 ? 'Tarifa vigente hasta el 5 de octubre de 2026.' : 'Tarifa vigente desde el 6 de octubre de 2026.'}</small></div>
      </div>
      <div className="form-grid">
        <label htmlFor="equipo">Nombre del equipo<input id="equipo" maxLength="120" value={equipo} onChange={(e) => { setEquipo(e.target.value.toUpperCase()); limpiarError('equipo') }} aria-invalid={Boolean(errores.equipo)} />{errores.equipo && <span className="field-error">{errores.equipo}</span>}</label>
        <label htmlFor="robot">Nombre del robot<input id="robot" maxLength="120" value={robot} onChange={(e) => { setRobot(e.target.value.toUpperCase()); limpiarError('robot') }} aria-invalid={Boolean(errores.robot)} />{errores.robot && <span className="field-error">{errores.robot}</span>}</label>
      </div>
      <div className="members-heading"><h2>Integrantes del equipo</h2><p>Dos participantes y un coach.</p></div>
      {integrantes.map((integrante, indice) => {
        const titulo = integrante.rol === 'COACH' ? 'Coach' : `Participante ${indice + 1}`
        return <fieldset className="member-fields" key={`${integrante.rol}-${indice}`}><legend>{titulo}</legend><div className="form-grid form-grid-four">
          {['nombres', 'apellidos', 'institucion', 'celular'].map((campo) => {
            const clave = `integrante-${indice}-${campo}`
            const etiqueta = campo === 'nombres' ? 'Nombres' : campo === 'apellidos' ? 'Apellidos' : campo === 'institucion' ? 'Institución' : 'Número celular'
            return <label key={campo} htmlFor={clave}>{etiqueta}<input id={clave} type={campo === 'celular' ? 'tel' : 'text'} inputMode={campo === 'celular' ? 'numeric' : undefined} maxLength={campo === 'celular' ? 10 : 150} value={integrante[campo]} onChange={(e) => { const valor = campo === 'celular' ? e.target.value.replace(/\D/g, '').slice(0, 10) : e.target.value.toUpperCase(); actualizarIntegrante(indice, campo, valor); limpiarError(clave) }} aria-invalid={Boolean(errores[clave])} />{errores[clave] && <span className="field-error">{errores[clave]}</span>}</label>
          })}
        </div></fieldset>
      })}
      <div className="payment-box"><h2>Comprobante de pago</h2><p>Adjunta la foto o PDF de la transferencia por ${tarifa}.00. Formatos permitidos: JPG, PNG, WEBP o PDF; máximo 5 MB.</p>
        <label className="file-input" htmlFor="comprobante"><span>{comprobante?.name || 'Seleccionar comprobante'}</span><input id="comprobante" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" onChange={(e) => { const archivo = e.target.files?.[0] || null; setComprobante(archivo); setErrores((actuales) => ({ ...actuales, comprobante: errorArchivo(archivo) })) }} aria-invalid={Boolean(errores.comprobante)} /></label>
        {errores.comprobante && <span className="field-error">{errores.comprobante}</span>}
      </div>
      {errores.servidor && <p className="form-error" role="alert">{errores.servidor}</p>}
      <button className="primary-button" type="submit" disabled={enviando}>{enviando ? 'Enviando inscripción...' : 'Inscribir equipo'} {!enviando && <span aria-hidden="true">→</span>}</button>
    </form>
  </section>
}
