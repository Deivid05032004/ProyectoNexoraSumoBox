import { useEffect, useMemo, useState } from 'react';
import { apiRequest } from './services/adminApi';
import './RegistrationFormBuilder.css';

const FIELD_TYPES = [
  ['short_text', 'Respuesta corta'], ['long_text', 'Párrafo'], ['email', 'Correo electrónico'],
  ['number', 'Número'], ['single_choice', 'Opción múltiple'], ['checkboxes', 'Casillas'], ['dropdown', 'Lista desplegable'],
];
const CHOICE_TYPES = new Set(['single_choice', 'checkboxes', 'dropdown']);
const newField = () => ({ id: crypto.randomUUID(), label: '', type: 'short_text', required: false, options: ['Opción 1'] });

export default function RegistrationFormBuilder({ onClose }) {
  const [events, setEvents] = useState([]);
  const [eventId, setEventId] = useState('');
  const [title, setTitle] = useState('Formulario de inscripción');
  const [description, setDescription] = useState('');
  const [fields, setFields] = useState([newField()]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selectedEvent = useMemo(() => events.find((event) => String(event.id) === eventId), [events, eventId]);

  useEffect(() => {
    let active = true;
    apiRequest('/api/v1/events?page=1&limit=100')
      .then((data) => {
        if (!active) return;
        const rows = data.items || [];
        setEvents(rows);
        if (rows.length) setEventId(String(rows[0].id));
        else setError('No hay competencias activas disponibles.');
      })
      .catch((err) => { if (active) setError(err.message || 'No se pudieron cargar las competencias.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function updateField(fieldId, changes) {
    setFields((current) => current.map((field) => field.id === fieldId ? { ...field, ...changes } : field));
  }

  function updateOption(field, optionIndex, value) {
    updateField(field.id, { options: field.options.map((option, index) => index === optionIndex ? value : option) });
  }

  async function submit(event) {
    event.preventDefault();
    setError('');
    setNotice('');
    if (!eventId) return setError('Selecciona una competencia.');
    if (!title.trim()) return setError('Escribe el título del formulario.');
    if (fields.some((field) => !field.label.trim())) return setError('Completa el enunciado de cada pregunta.');
    if (fields.some((field) => CHOICE_TYPES.has(field.type) && field.options.filter((option) => option.trim()).length < 2)) {
      return setError('Cada pregunta con opciones necesita al menos dos opciones.');
    }

    const payload = {
      organization_name: 'UTA SUMO ROBOTICS CUP',
      form_title: title.trim(),
      form_description: description.trim() || null,
      form_instructions: null,
      payment_instructions: null,
      payment_methods: [],
      contact_email: null,
      contact_phone: null,
      receipt_message: null,
      currency: 'USD',
      is_enabled: true,
      custom_fields: fields.map(({ id, label, type, required, options }) => ({
        id, label: label.trim(), type, required,
        options: CHOICE_TYPES.has(type) ? options.map((option) => option.trim()).filter(Boolean) : [],
      })),
    };

    setSaving(true);
    try {
      const result = await apiRequest(`/api/v1/admin/events/${eventId}/registration-config`, {
        method: 'PUT', body: JSON.stringify(payload),
      });
      setNotice(`Configuración básica guardada para ${selectedEvent?.name || 'la competencia'}. El backend no confirmó los campos personalizados.`);
      setTitle(result.form_title || title);
    } catch (err) {
      const detail = String(err.message || 'Error desconocido.');
      if (/custom_fields|extra inputs are not permitted|extra_forbidden/i.test(detail)) {
        setError('El backend rechazó las preguntas personalizadas: la ruta PUT /api/v1/admin/events/{event_id}/registration-config no acepta el campo custom_fields. Se requiere ampliar el esquema del backend antes de guardar este formulario.');
      } else {
        setError(detail);
      }
    } finally { setSaving(false); }
  }

  return <div className="registration-builder-overlay" role="dialog" aria-modal="true" aria-labelledby="registration-builder-title">
    <form className="registration-builder" onSubmit={submit}>
      <header className="registration-builder-header">
        <div><span className="registration-builder-kicker">DISEÑADOR DE INSCRIPCIONES</span><h2 id="registration-builder-title">Crear formulario</h2>
          <p>Configura las preguntas y opciones para una competencia.</p></div>
        <button type="button" className="registration-builder-close" onClick={onClose} aria-label="Cerrar">×</button>
      </header>

      {error && <div className="registration-builder-alert" role="alert">{error}</div>}
      {notice && <div className="registration-builder-notice" role="status">{notice}</div>}
      {loading ? <p className="registration-builder-loading">Cargando competencias…</p> : <>
        <label className="registration-builder-label">Competencia
          <select value={eventId} onChange={(event) => setEventId(event.target.value)} disabled={!events.length}>
            {events.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.edition_year}</option>)}
          </select>
        </label>
        <label className="registration-builder-label">Título del formulario
          <input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} placeholder="Inscripción a la competencia" />
        </label>
        <label className="registration-builder-label">Descripción
          <textarea value={description} maxLength={2000} rows={2} onChange={(event) => setDescription(event.target.value)} placeholder="Describe el formulario para los participantes" />
        </label>

        <div className="registration-builder-fields-header"><div><h3>Preguntas</h3><p>Elige tipo, opciones y si la respuesta es obligatoria.</p></div>
          <button type="button" className="registration-builder-add" onClick={() => setFields((current) => [...current, newField()])}>＋ Agregar pregunta</button></div>

        <div className="registration-builder-fields">
          {fields.map((field, index) => <article className="registration-builder-field" key={field.id}>
            <div className="registration-builder-field-top"><span>Pregunta {index + 1}</span>
              <button type="button" onClick={() => setFields((current) => current.length > 1 ? current.filter((item) => item.id !== field.id) : current)}
                disabled={fields.length === 1} aria-label={`Eliminar pregunta ${index + 1}`}>Eliminar</button></div>
            <div className="registration-builder-field-grid">
              <label className="registration-builder-label">Enunciado
                <input value={field.label} maxLength={200} onChange={(event) => updateField(field.id, { label: event.target.value })} placeholder="Ej. Nombre del equipo" />
              </label>
              <label className="registration-builder-label">Tipo de respuesta
                <select value={field.type} onChange={(event) => updateField(field.id, { type: event.target.value })}>
                  {FIELD_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            </div>
            {CHOICE_TYPES.has(field.type) && <div className="registration-builder-options">
              <strong>Opciones</strong>
              {field.options.map((option, optionIndex) => <div className="registration-builder-option" key={`${field.id}-${optionIndex}`}>
                <input value={option} maxLength={100} onChange={(event) => updateOption(field, optionIndex, event.target.value)} aria-label={`Opción ${optionIndex + 1}`} />
                <button type="button" onClick={() => updateField(field.id, { options: field.options.length > 1 ? field.options.filter((_, index) => index !== optionIndex) : [''] })}>×</button>
              </div>)}
              <button type="button" className="registration-builder-add-option" onClick={() => updateField(field.id, { options: [...field.options, `Opción ${field.options.length + 1}`] })}>＋ Agregar opción</button>
            </div>}
            <label className="registration-builder-required"><input type="checkbox" checked={field.required} onChange={(event) => updateField(field.id, { required: event.target.checked })} /> Respuesta obligatoria</label>
          </article>)}
        </div>
        <footer className="registration-builder-footer">
          <span>Competencia seleccionada: {selectedEvent?.name || '—'}</span>
          <div><button type="button" className="registration-builder-cancel" onClick={onClose}>Cancelar</button>
            <button type="submit" className="registration-builder-submit" disabled={saving || !events.length}>{saving ? 'Enviando…' : 'Enviar al backend'}</button></div>
        </footer>
      </>}
    </form>
  </div>;
}
