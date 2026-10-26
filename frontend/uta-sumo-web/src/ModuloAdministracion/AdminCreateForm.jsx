import { useState } from 'react';
import './AdminCreateForm.css';

export default function AdminCreateForm({ onClose }) {
  const [message, setMessage] = useState('');
  function submit(event) {
    event.preventDefault();
    setMessage('Pendiente de implementación en backend.');
    console.log('Registro de administrador pendiente de implementación en backend.');
  }
  return <div className="admin-create-overlay" role="dialog" aria-modal="true" aria-labelledby="admin-create-title">
    <form className="admin-create-card" onSubmit={submit}>
      <button type="button" className="admin-create-close" onClick={onClose} aria-label="Cerrar">×</button>
      <p className="admin-eyebrow">GESTIÓN DE ACCESOS</p>
      <h2 id="admin-create-title">Nuevo administrador</h2>
      <p>Completa los datos para preparar una nueva cuenta administrativa.</p>
      <label>Nombre<input required name="first_name" autoComplete="given-name" /></label>
      <label>Apellido<input required name="last_name" autoComplete="family-name" /></label>
      <label>Correo electrónico<input required type="email" name="email" autoComplete="email" /></label>
      <label>Rol<select name="role" defaultValue="ADMIN"><option value="ADMIN">Administrador</option><option value="EVENT_MANAGER">Gestor de evento</option></select></label>
      {message && <div className="admin-create-notice" role="status">{message}</div>}
      <div className="admin-create-actions"><button type="button" onClick={onClose}>Cerrar</button><button type="submit">Registrar administrador</button></div>
    </form>
  </div>;
}
